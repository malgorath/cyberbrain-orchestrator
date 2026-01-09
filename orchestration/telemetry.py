"""
Telemetry Collectors for System Health Monitoring

Components:
- GPUMetricsCollector: Collects and updates GPU utilization metrics
- DockerHealthChecker: Checks container health status
- LLMHealthMonitor: Monitors LLM endpoint health and call statistics
- TelemetryAggregator: Aggregates all telemetry into unified report

Design by Contract:
- No LLM prompts or responses stored (token counts only)
- All metrics timestamped for trend analysis
- Unavailable resources tracked separately
- Success/failure rates calculated for endpoints
"""
from django.utils import timezone
from django.db.models import Q, Avg, Count
from core.models import (
    GPUState, ContainerAllowlist, LLMCall
)
from typing import Dict, Any, Optional, List
import statistics


class GPUMetricsCollector:
    """Collects GPU metrics and updates GPUState records"""
    
    def collect_gpu_metrics(self, metrics: Dict[str, Dict[str, Any]]) -> None:
        """
        Update GPU metrics from collected data.
        
        Args:
            metrics: Dict mapping gpu_id to metrics dict with:
                - used_vram_mb: Currently used VRAM
                - free_vram_mb: Available VRAM
                - utilization_percent: Utilization percentage (0-100)
        
        Contract:
        - Updates last_updated timestamp
        - Marks GPU as available if data collected successfully
        - Preserves active_workers count (not overwritten)
        """
        for gpu_id, data in metrics.items():
            try:
                gpu = GPUState.objects.get(gpu_id=gpu_id)
                gpu.used_vram_mb = data.get("used_vram_mb", gpu.used_vram_mb)
                gpu.free_vram_mb = data.get("free_vram_mb", gpu.free_vram_mb)
                gpu.utilization_percent = data.get("utilization_percent", gpu.utilization_percent)
                gpu.is_available = True  # Mark as available since we collected data
                gpu.save()
            except GPUState.DoesNotExist:
                # Create new GPU record if not found
                GPUState.objects.create(
                    gpu_id=gpu_id,
                    gpu_name=data.get("gpu_name", f"GPU {gpu_id}"),
                    total_vram_mb=data.get("total_vram_mb", 0),
                    used_vram_mb=data.get("used_vram_mb", 0),
                    free_vram_mb=data.get("free_vram_mb", 0),
                    utilization_percent=data.get("utilization_percent", 0),
                    is_available=True
                )
    
    def mark_gpu_unavailable(self, gpu_id: str) -> None:
        """Mark GPU as unavailable due to collection failure"""
        try:
            gpu = GPUState.objects.get(gpu_id=gpu_id)
            gpu.is_available = False
            gpu.save()
        except GPUState.DoesNotExist:
            pass


class DockerHealthChecker:
    """Checks Docker container health status"""
    
    def check_container_health(
        self, 
        health_status: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Check and record container health status.
        
        Args:
            health_status: Dict mapping container_id to status info:
                - running: bool
                - status: str (e.g., "healthy", "exited")
                - uptime_seconds: int
        
        Returns:
            Dict of checked containers with health results
        
        Contract:
        - Only checks allowlisted containers
        - Disabled containers excluded from results
        - Marks unhealthy if not running
        """
        results = {}
        
        # Get enabled containers
        enabled_containers = ContainerAllowlist.objects.filter(enabled=True)
        container_ids = set(c.container_id for c in enabled_containers)
        
        for container_id, status_data in health_status.items():
            if container_id not in container_ids:
                continue  # Skip disabled containers
            
            is_running = status_data.get("running", False)
            healthy = is_running and status_data.get("status") != "exited"
            
            results[container_id] = {
                "healthy": healthy,
                "status": status_data.get("status", "unknown"),
                "uptime_seconds": status_data.get("uptime_seconds", 0),
            }
        
        return results


class LLMHealthMonitor:
    """Monitors LLM endpoint health and statistics"""
    
    def check_llm_endpoints(
        self, 
        endpoint_status: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Check LLM endpoint reachability and latency.
        
        Args:
            endpoint_status: Dict mapping endpoint name to status:
                - reachable: bool
                - latency_ms: int (or None if unreachable)
                - error: str (optional, if unreachable)
                - last_check: ISO datetime string
        
        Returns:
            Dict of endpoint health results
        
        Contract:
        - Marks unhealthy if unreachable
        - Includes error messages for debugging
        """
        results = {}
        
        for endpoint_name, status_data in endpoint_status.items():
            reachable = status_data.get("reachable", False)
            
            result = {
                "healthy": reachable,
                "latency_ms": status_data.get("latency_ms"),
                "last_check": status_data.get("last_check"),
            }
            
            if not reachable:
                result["error"] = status_data.get("error", "Unknown error")
            
            results[endpoint_name] = result
        
        return results
    
    def get_llm_stats(self, endpoint_name: str) -> Dict[str, Any]:
        """
        Get LLM endpoint statistics from call history.
        
        Args:
            endpoint_name: Endpoint identifier (e.g., 'vllm', 'llama_cpp')
        
        Returns:
            Dict with statistics:
            - total_calls: number of calls
            - p50_latency_ms: median latency
            - p95_latency_ms: 95th percentile
            - p99_latency_ms: 99th percentile
            - avg_tokens: average total tokens per call
        
        Contract:
        - No LLM content in statistics (tokens only)
        - Percentiles calculated from actual durations
        """
        calls = LLMCall.objects.filter(endpoint=endpoint_name)
        
        if not calls.exists():
            return {
                "total_calls": 0,
                "p50_latency_ms": None,
                "p95_latency_ms": None,
                "p99_latency_ms": None,
                "avg_tokens": 0,
            }
        
        total_calls = calls.count()
        
        # Latency percentiles from duration_ms
        durations = list(
            calls.exclude(duration_ms__isnull=True)
            .values_list('duration_ms', flat=True)
            .order_by('duration_ms')
        )
        
        p50 = None
        p95 = None
        p99 = None
        
        if durations:
            p50 = statistics.median(durations)
            if len(durations) >= 20:
                p95 = durations[int(len(durations) * 0.95)]
                p99 = durations[int(len(durations) * 0.99)]
            else:
                # For small datasets, use quartiles
                p95 = max(durations) if durations else None
                p99 = max(durations) if durations else None
        
        # Average tokens (no content)
        avg_tokens = calls.aggregate(
            avg=Avg('total_tokens')
        )['avg'] or 0
        
        return {
            "total_calls": total_calls,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "avg_tokens": int(avg_tokens) if avg_tokens else 0,
        }


class TelemetryAggregator:
    """Aggregates all telemetry into unified system health report"""
    
    def __init__(self):
        self.gpu_collector = GPUMetricsCollector()
        self.docker_checker = DockerHealthChecker()
        self.llm_monitor = LLMHealthMonitor()
    
    def get_system_health(self) -> Dict[str, Any]:
        """
        Generate comprehensive system health report.
        
        Returns:
            Dict with sections:
            - gpu_metrics: List of GPU states
            - container_health: Dict of container statuses
            - llm_endpoints: Dict of LLM endpoint stats
            - timestamp: When report was generated
        
        Contract:
        - NO sensitive data (prompts/responses)
        - All metrics timestamped
        - Comprehensive but privacy-preserving
        """
        # GPU metrics
        gpu_metrics = []
        for gpu in GPUState.objects.all().order_by('gpu_id'):
            gpu_metrics.append({
                "gpu_id": gpu.gpu_id,
                "gpu_name": gpu.gpu_name,
                "total_vram_mb": gpu.total_vram_mb,
                "used_vram_mb": gpu.used_vram_mb,
                "free_vram_mb": gpu.free_vram_mb,
                "utilization_percent": gpu.utilization_percent,
                "is_available": gpu.is_available,
                "active_workers": gpu.active_workers,
                "last_updated": gpu.last_updated.isoformat() if gpu.last_updated else None,
            })
        
        # Container health (mock for now, would call Docker health API)
        container_health = {}
        for container in ContainerAllowlist.objects.filter(enabled=True):
            container_health[container.container_id] = {
                "name": container.container_name,
                "description": container.description,
                "enabled": container.enabled,
            }
        
        # LLM endpoint stats
        llm_endpoints = {}
        
        # Get unique endpoints from call history
        endpoint_names = LLMCall.objects.values_list('endpoint', flat=True).distinct()
        for endpoint in endpoint_names:
            llm_endpoints[endpoint] = self.llm_monitor.get_llm_stats(endpoint)
        
        return {
            "timestamp": timezone.now().isoformat(),
            "gpu_metrics": gpu_metrics,
            "container_health": container_health,
            "llm_endpoints": llm_endpoints,
        }
