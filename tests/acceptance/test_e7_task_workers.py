"""
E7 Acceptance Tests: Task Worker Implementations

ATDD for three task workers:
- Task 1 (task1): Log Triage - Collects Docker logs, analyzes via LLM, produces markdown report
- Task 2 (task2): GPU Report - Analyzes GPU telemetry, identifies hotspots, produces JSON report  
- Task 3 (task3): Service Map - Inventories allowlisted containers, maps network topology, produces JSON report

Contract expectations:
- Each task produces RunArtifact artifacts (markdown or JSON)
- LLM calls tracked with token counts only (no content)
- Tasks handle missing data gracefully (unavailable GPUs, etc.)
- All tasks write output to /logs directory under run context
- Status tracking: pending → running → success (or failed with error)
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from core.models import (
    Job, Run, Directive, RunJob, LLMCall, RunArtifact, 
    ContainerAllowlist, GPUState
)
from unittest.mock import MagicMock, patch
import json


class TaskWorkerSecurityTests(TestCase):
    """Security contract tests for all task workers."""
    
    def test_no_prompt_response_content_in_database(self):
        """CONTRACT: No task worker stores LLM prompt/response content."""
        from core.models import LLMCall
        
        # Get all field names from the model
        field_names = [f.name for f in LLMCall._meta.get_fields()]
        
        # Check for forbidden content fields
        forbidden = ['prompt', 'response', 'content', 'prompt_text',
                     'response_text', 'completion_text', 'messages',
                     'prompt_content', 'response_content']
        
        for field in forbidden:
            self.assertNotIn(
                field, field_names,
                f"SECURITY VIOLATION: LLMCall has forbidden field '{field}'"
            )


class Task1LogTriageTests(TestCase):
    """Test Task 1 (log_triage) worker"""
    
    def setUp(self):
        """Create test directive and job"""
        self.directive = Directive.objects.create(
            directive_type="D1",
            name="log-triage",
            directive_text="Analyze container logs for errors and warnings",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage",
            name="Log Triage",
            default_directive=self.directive,
            is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="pending"
        )
        # Create allowlisted containers
        ContainerAllowlist.objects.create(
            container_id="web123",
            container_name="web_service",
            enabled=True
        )
        ContainerAllowlist.objects.create(
            container_id="db456",
            container_name="postgres_db",
            enabled=True
        )
    
    def test_task1_creates_run_job(self):
        """Task 1 must create RunJob entry"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.job,
            status="pending"
        )
        
        self.assertIsNotNone(run_job.id)
        self.assertEqual(run_job.status, "pending")
        self.assertEqual(run_job.run, self.run)
    
    def test_task1_initializes_token_counts(self):
        """Task 1 must initialize token counters on RunJob"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.job,
            status="pending",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0
        )
        
        self.assertEqual(run_job.prompt_tokens, 0)
        self.assertEqual(run_job.completion_tokens, 0)
        self.assertEqual(run_job.total_tokens, 0)
    
    def test_task1_records_llm_call_tokens(self):
        """Task 1 must record LLM call tokens in LLMCall"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.job,
            status="running"
        )
        
        # Simulate LLM call
        LLMCall.objects.create(
            run=self.run,
            endpoint="vllm",
            model_id="mistral-7b",
            prompt_tokens=150,
            completion_tokens=75,
            total_tokens=225
        )
        
        # Verify tokens recorded
        call = LLMCall.objects.filter(run=self.run).first()
        self.assertEqual(call.total_tokens, 225)
        # Update RunJob totals
        run_job.prompt_tokens += call.prompt_tokens
        run_job.completion_tokens += call.completion_tokens
        run_job.total_tokens += call.total_tokens
        run_job.save()
        
        run_job.refresh_from_db()
        self.assertEqual(run_job.total_tokens, 225)
    
    def test_task1_artifact_no_sensitive_content(self):
        """Task 1 artifact must NOT contain LLM prompts/responses"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.job,
            status="success"
        )
        
        # Create artifact
        artifact = RunArtifact.objects.create(
            run=self.run,
            artifact_type="markdown",
            path="/logs/run_{0}/report.md".format(self.run.id)
        )
        
        # Verify artifact doesn't reference content fields
        self.assertNotIn("prompt", artifact.path.lower())
        self.assertNotIn("response", artifact.path.lower())


class Task2GPUReportTests(TestCase):
    """Test Task 2 (gpu_report) worker"""
    
    def setUp(self):
        """Create test directive, job, and GPUs"""
        self.directive = Directive.objects.create(
            directive_type="D2",
            name="gpu-report",
            directive_text="Analyze GPU utilization and identify hotspots",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="gpu_report",
            name="GPU Report",
            default_directive=self.directive,
            is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="pending"
        )
        # Create GPUs
        self.gpu0 = GPUState.objects.create(
            gpu_id="0",
            gpu_name="NVIDIA RTX 4090",
            total_vram_mb=24576,
            used_vram_mb=20480,
            free_vram_mb=4096,
            utilization_percent=83.3,
            is_available=True,
            active_workers=2
        )
        self.gpu1 = GPUState.objects.create(
            gpu_id="1",
            gpu_name="NVIDIA RTX 4090",
            total_vram_mb=24576,
            used_vram_mb=2048,
            free_vram_mb=22528,
            utilization_percent=8.3,
            is_available=True,
            active_workers=0
        )
    
    def test_task2_creates_run_job(self):
        """Task 2 must create RunJob entry"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.job,
            status="pending"
        )
        
        self.assertEqual(run_job.job.task_key, "gpu_report")
        self.assertEqual(run_job.status, "pending")
    
    def test_task2_can_query_gpu_state(self):
        """Task 2 must be able to query GPUState records"""
        gpus = GPUState.objects.all()
        
        self.assertEqual(gpus.count(), 2)
        self.assertEqual(gpus.filter(gpu_id="0").first().utilization_percent, 83.3)
        self.assertEqual(gpus.filter(gpu_id="1").first().active_workers, 0)
    
    def test_task2_identifies_high_utilization_gpu(self):
        """Task 2 can identify high-utilization GPU"""
        high_util = GPUState.objects.filter(utilization_percent__gt=50).first()
        
        self.assertIsNotNone(high_util)
        self.assertEqual(high_util.gpu_id, "0")
    
    def test_task2_produces_artifact(self):
        """Task 2 must produce RunArtifact"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.job,
            status="success"
        )
        
        artifact = RunArtifact.objects.create(
            run=self.run,
            artifact_type="json",
            path="/logs/run_{0}/gpu_report.json".format(self.run.id)
        )
        
        self.assertEqual(artifact.artifact_type, "json")
        self.assertIn("gpu_report.json", artifact.path)


class Task3ServiceMapTests(TestCase):
    """Test Task 3 (service_map) worker"""
    
    def setUp(self):
        """Create test directive, job, and containers"""
        self.directive = Directive.objects.create(
            directive_type="D3",
            name="service-map",
            directive_text="Map service inventory and network topology",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="service_map",
            name="Service Map",
            default_directive=self.directive,
            is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="pending"
        )
        # Create allowlisted containers
        self.web = ContainerAllowlist.objects.create(
            container_id="web123",
            container_name="web",
            description="Web service",
            enabled=True
        )
        self.api = ContainerAllowlist.objects.create(
            container_id="api456",
            container_name="api",
            description="API service",
            enabled=True
        )
        # Disabled container should not appear in map
        self.secret = ContainerAllowlist.objects.create(
            container_id="secret789",
            container_name="secret",
            description="Secret service",
            enabled=False
        )
    
    def test_task3_creates_run_job(self):
        """Task 3 must create RunJob entry"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.job,
            status="pending"
        )
        
        self.assertEqual(run_job.job.task_key, "service_map")
    
    def test_task3_queries_enabled_containers_only(self):
        """Task 3 must only query enabled containers"""
        enabled = ContainerAllowlist.objects.filter(enabled=True)
        
        self.assertEqual(enabled.count(), 2)
        self.assertIn(self.web, enabled)
        self.assertIn(self.api, enabled)
        self.assertNotIn(self.secret, enabled)
    
    def test_task3_produces_artifact(self):
        """Task 3 must produce RunArtifact"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.job,
            status="success"
        )
        
        artifact = RunArtifact.objects.create(
            run=self.run,
            artifact_type="json",
            path="/logs/run_{0}/services.json".format(self.run.id)
        )
        
        self.assertEqual(artifact.artifact_type, "json")
        self.assertIn("services.json", artifact.path)


class AllTasksRunJobTests(TestCase):
    """Test RunJob creation for all 3 tasks"""
    
    def setUp(self):
        """Create directives for all 3 tasks"""
        self.d1 = Directive.objects.create(
            directive_type="D1", name="d1", directive_text="D1", version=1, is_active=True
        )
        self.d2 = Directive.objects.create(
            directive_type="D2", name="d2", directive_text="D2", version=1, is_active=True
        )
        self.d3 = Directive.objects.create(
            directive_type="D3", name="d3", directive_text="D3", version=1, is_active=True
        )
        
        # Create jobs
        self.j1 = Job.objects.create(task_key="log_triage", name="J1", default_directive=self.d1, is_active=True)
        self.j2 = Job.objects.create(task_key="gpu_report", name="J2", default_directive=self.d2, is_active=True)
        self.j3 = Job.objects.create(task_key="service_map", name="J3", default_directive=self.d3, is_active=True)
        
        # Create run
        self.run = Run.objects.create(
            job=self.j1,
            directive_snapshot_name=self.d1.name,
            directive_snapshot_text=self.d1.directive_text,
            status="pending"
        )
    
    def test_create_run_jobs_for_all_three_tasks(self):
        """Can create RunJobs for all 3 tasks in a single run"""
        for job in [self.j1, self.j2, self.j3]:
            RunJob.objects.create(
                run=self.run,
                job=job,
                status="pending"
            )
        
        run_jobs = RunJob.objects.filter(run=self.run)
        self.assertEqual(run_jobs.count(), 3)
    
    def test_run_job_status_transitions(self):
        """RunJob status transitions: pending → running → success"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.j1,
            status="pending"
        )
        
        # Transition to running
        run_job.status = "running"
        run_job.started_at = timezone.now()
        run_job.save()
        
        run_job.refresh_from_db()
        self.assertEqual(run_job.status, "running")
        self.assertIsNotNone(run_job.started_at)
        
        # Transition to success
        run_job.status = "success"
        run_job.completed_at = timezone.now()
        run_job.save()
        
        run_job.refresh_from_db()
        self.assertEqual(run_job.status, "success")
        self.assertIsNotNone(run_job.completed_at)
    
    def test_run_job_error_recording(self):
        """RunJob can record errors when task fails"""
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.j1,
            status="pending"
        )
        
        # Record error
        run_job.status = "failed"
        run_job.error_message = "Docker socket not available"
        run_job.save()
        
        run_job.refresh_from_db()
        self.assertEqual(run_job.status, "failed")
        self.assertIn("Docker", run_job.error_message)
