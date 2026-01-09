"""
E5 Acceptance Tests: Telemetry Collectors

ATDD for system health monitoring:
- GPU metrics collection and storage in GPUState
- Docker container health checking
- LLM endpoint health/availability tracking
- Telemetry aggregation without storing sensitive content

Contract expectations:
- GPU metrics include VRAM usage, utilization percentage, availability
- Docker stats collected for all allowlisted containers
- LLM endpoint checks verify connectivity, latency, response format
- No sensitive data (prompts, responses) stored in telemetry
- Timestamps track when metrics were collected
"""
from django.test import TestCase
from django.utils import timezone
from core.models import (
    GPUState, ContainerAllowlist, LLMCall, Run, Job, Directive
)
from orchestration.telemetry import (
    GPUMetricsCollector, DockerHealthChecker, LLMHealthMonitor
)
from unittest.mock import MagicMock, patch
import json


class GPUMetricsCollectorTests(TestCase):
    """Test GPU metrics collection and storage"""
    
    def setUp(self):
        """Create test GPU states"""
        self.gpu0 = GPUState.objects.create(
            gpu_id="0",
            gpu_name="NVIDIA RTX 4090",
            total_vram_mb=24576,
            used_vram_mb=0,
            free_vram_mb=24576,
            utilization_percent=0.0,
            is_available=True,
            active_workers=0
        )
        self.gpu1 = GPUState.objects.create(
            gpu_id="1",
            gpu_name="NVIDIA RTX 4090",
            total_vram_mb=24576,
            used_vram_mb=12288,
            free_vram_mb=12288,
            utilization_percent=50.0,
            is_available=True,
            active_workers=1
        )
        self.collector = GPUMetricsCollector()
    
    def test_collect_updates_gpu_metrics(self):
        """Collecting metrics must update GPUState records"""
        # Simulate new metrics from nvidia-smi or similar
        new_metrics = {
            "0": {
                "used_vram_mb": 1024,
                "free_vram_mb": 23552,
                "utilization_percent": 10.0,
            },
            "1": {
                "used_vram_mb": 8192,
                "free_vram_mb": 16384,
                "utilization_percent": 33.3,
            },
        }
        
        self.collector.collect_gpu_metrics(new_metrics)
        
        # Verify GPU 0 updated
        gpu0 = GPUState.objects.get(gpu_id="0")
        self.assertEqual(gpu0.used_vram_mb, 1024)
        self.assertEqual(gpu0.free_vram_mb, 23552)
        self.assertAlmostEqual(gpu0.utilization_percent, 10.0, places=1)
        
        # Verify GPU 1 updated
        gpu1 = GPUState.objects.get(gpu_id="1")
        self.assertEqual(gpu1.used_vram_mb, 8192)
        self.assertEqual(gpu1.free_vram_mb, 16384)
        self.assertAlmostEqual(gpu1.utilization_percent, 33.3, places=1)
    
    def test_collect_timestamps_metrics(self):
        """GPU metrics collection must timestamp when updated"""
        before = timezone.now()
        
        new_metrics = {
            "0": {
                "used_vram_mb": 2048,
                "free_vram_mb": 22528,
                "utilization_percent": 8.3,
            }
        }
        
        self.collector.collect_gpu_metrics(new_metrics)
        
        after = timezone.now()
        gpu0 = GPUState.objects.get(gpu_id="0")
        
        self.assertGreaterEqual(gpu0.last_updated, before)
        self.assertLessEqual(gpu0.last_updated, after)
    
    def test_gpu_metrics_marks_unavailable_if_unreachable(self):
        """GPU should be marked unavailable if metrics collection fails"""
        self.collector.mark_gpu_unavailable("0")
        
        gpu0 = GPUState.objects.get(gpu_id="0")
        self.assertFalse(gpu0.is_available, "GPU should be unavailable after failed collection")
    
    def test_gpu_metrics_recovered_when_reachable(self):
        """GPU should be marked available again when reachable"""
        # Mark unavailable first
        gpu0 = GPUState.objects.get(gpu_id="0")
        gpu0.is_available = False
        gpu0.save()
        
        # Recover when metrics collected
        new_metrics = {
            "0": {
                "used_vram_mb": 512,
                "free_vram_mb": 24064,
                "utilization_percent": 2.1,
            }
        }
        
        self.collector.collect_gpu_metrics(new_metrics)
        
        gpu0.refresh_from_db()
        self.assertTrue(gpu0.is_available, "GPU should be available again after successful collection")


class DockerHealthCheckerTests(TestCase):
    """Test Docker container health checking"""
    
    def setUp(self):
        """Create allowlisted containers"""
        self.container1 = ContainerAllowlist.objects.create(
            container_id="abc123def456",
            container_name="orchestrator_web",
            description="Main web service",
            enabled=True
        )
        self.container2 = ContainerAllowlist.objects.create(
            container_id="xyz789uvw012",
            container_name="orchestrator_postgres",
            description="PostgreSQL database",
            enabled=True
        )
        self.checker = DockerHealthChecker()
    
    def test_check_container_health_status(self):
        """Checking health must verify container is running"""
        # Simulate health check results
        health_status = {
            "abc123def456": {
                "running": True,
                "status": "healthy",
                "uptime_seconds": 3600,
            },
            "xyz789uvw012": {
                "running": True,
                "status": "healthy",
                "uptime_seconds": 7200,
            }
        }
        
        results = self.checker.check_container_health(health_status)
        
        self.assertEqual(len(results), 2)
        self.assertTrue(results["abc123def456"]["healthy"])
        self.assertEqual(results["abc123def456"]["uptime_seconds"], 3600)
    
    def test_check_container_unhealthy_status(self):
        """Container marked unhealthy if not running"""
        health_status = {
            "abc123def456": {
                "running": False,
                "status": "exited",
                "uptime_seconds": 0,
            }
        }
        
        results = self.checker.check_container_health(health_status)
        
        self.assertFalse(results["abc123def456"]["healthy"], "Container should be unhealthy if not running")
    
    def test_health_check_excludes_disabled_containers(self):
        """Health check should skip disabled containers"""
        # Disable one container
        self.container2.enabled = False
        self.container2.save()
        
        health_status = {
            "abc123def456": {"running": True, "status": "healthy"},
            "xyz789uvw012": {"running": False, "status": "exited"},  # This should be ignored
        }
        
        results = self.checker.check_container_health(health_status)
        
        self.assertIn("abc123def456", results)
        self.assertNotIn("xyz789uvw012", results)


class LLMHealthMonitorTests(TestCase):
    """Test LLM endpoint health monitoring"""
    
    def setUp(self):
        """Create test data"""
        self.directive = Directive.objects.create(
            directive_type="D1",
            name="test-directive",
            directive_text="Test directive",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage",
            name="Test Job",
            default_directive=self.directive,
            is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="running"
        )
        self.monitor = LLMHealthMonitor()
    
    def test_monitor_llm_endpoint_connectivity(self):
        """Monitoring must verify LLM endpoint is reachable"""
        endpoint_status = {
            "vllm": {
                "reachable": True,
                "latency_ms": 45,
                "last_check": "2026-01-08T20:25:00Z",
            },
            "llama_cpp": {
                "reachable": True,
                "latency_ms": 120,
                "last_check": "2026-01-08T20:25:00Z",
            }
        }
        
        results = self.monitor.check_llm_endpoints(endpoint_status)
        
        self.assertTrue(results["vllm"]["healthy"])
        self.assertEqual(results["vllm"]["latency_ms"], 45)
        self.assertTrue(results["llama_cpp"]["healthy"])
        self.assertEqual(results["llama_cpp"]["latency_ms"], 120)
    
    def test_monitor_llm_endpoint_unreachable(self):
        """Endpoint marked unhealthy if unreachable"""
        endpoint_status = {
            "vllm": {
                "reachable": False,
                "latency_ms": None,
                "error": "Connection refused",
                "last_check": "2026-01-08T20:25:00Z",
            }
        }
        
        results = self.monitor.check_llm_endpoints(endpoint_status)
        
        self.assertFalse(results["vllm"]["healthy"])
        self.assertIn("error", results["vllm"])
    
    def test_monitor_tracks_llm_call_success_rate(self):
        """Monitoring must track LLM call success/failure rate"""
        # Create several LLM calls (only successful calls stored)
        for i in range(10):
            LLMCall.objects.create(
                run=self.run,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                duration_ms=200
            )
        
        stats = self.monitor.get_llm_stats("vllm")
        
        self.assertEqual(stats["total_calls"], 10)
    
    def test_monitor_tracks_llm_latency_percentiles(self):
        """Monitoring must calculate latency percentiles"""
        # Create LLM calls with various latencies
        latencies = [100, 150, 200, 250, 300, 350, 400, 450, 500, 550]
        for latency in latencies:
            LLMCall.objects.create(
                run=self.run,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                duration_ms=latency
            )
        
        stats = self.monitor.get_llm_stats("vllm")
        
        self.assertEqual(stats["total_calls"], 10)
        self.assertIsNotNone(stats["p50_latency_ms"])
        self.assertIsNotNone(stats["p95_latency_ms"])
        self.assertIsNotNone(stats["p99_latency_ms"])
        # p50 should be around 300 (median of 100-550)
        self.assertGreater(stats["p50_latency_ms"], 200)
        self.assertLess(stats["p50_latency_ms"], 400)
    
    def test_monitor_no_sensitive_data_in_telemetry(self):
        """Telemetry must NEVER store prompts or responses"""
        # Create LLM call
        call = LLMCall.objects.create(
            run=self.run,
            endpoint="vllm",
            model_id="mistral-7b",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            duration_ms=200
        )
        
        # Verify no prompt/response fields exist
        field_names = [f.name for f in LLMCall._meta.get_fields()]
        forbidden_fields = ['prompt', 'response', 'content', 'prompt_text', 
                          'response_text', 'completion_text', 'messages']
        
        for forbidden in forbidden_fields:
            self.assertNotIn(forbidden, field_names, 
                           f"LLMCall should not have {forbidden} field (security guardrail)")


class TelemetryAggregationTests(TestCase):
    """Test telemetry aggregation and reporting"""
    
    def setUp(self):
        """Create test data"""
        # Create GPUs
        self.gpu0 = GPUState.objects.create(
            gpu_id="0",
            gpu_name="NVIDIA RTX 4090",
            total_vram_mb=24576,
            used_vram_mb=1024,
            free_vram_mb=23552,
            utilization_percent=4.2,
            is_available=True,
            active_workers=0
        )
        self.gpu1 = GPUState.objects.create(
            gpu_id="1",
            gpu_name="NVIDIA RTX 4090",
            total_vram_mb=24576,
            used_vram_mb=18432,
            free_vram_mb=6144,
            utilization_percent=75.0,
            is_available=True,
            active_workers=2
        )
        
        # Create containers
        ContainerAllowlist.objects.create(
            container_id="web123",
            container_name="web",
            enabled=True
        )
        ContainerAllowlist.objects.create(
            container_id="db456",
            container_name="postgres",
            enabled=True
        )
        
        # Create directive and run
        self.directive = Directive.objects.create(
            directive_type="D1",
            name="test-directive",
            directive_text="Test",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage",
            name="Test Job",
            default_directive=self.directive,
            is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="running"
        )
        
        # Create LLM calls
        for i in range(5):
            LLMCall.objects.create(
                run=self.run,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                duration_ms=200
            )
    
    def test_aggregate_system_health_report(self):
        """Aggregating telemetry must create system health report"""
        from orchestration.telemetry import TelemetryAggregator
        
        aggregator = TelemetryAggregator()
        report = aggregator.get_system_health()
        
        # GPU metrics
        self.assertIn("gpu_metrics", report)
        self.assertEqual(len(report["gpu_metrics"]), 2)
        
        # Container metrics  
        self.assertIn("container_health", report)
        
        # LLM metrics
        self.assertIn("llm_endpoints", report)
        self.assertIn("vllm", report["llm_endpoints"])
        
        # No sensitive data in report
        report_str = json.dumps(report, default=str)
        self.assertNotIn("prompt", report_str.lower())
        self.assertNotIn("response", report_str.lower())
