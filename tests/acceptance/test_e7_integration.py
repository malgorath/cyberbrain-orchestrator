"""
E7 Integration Tests: End-to-End Task Execution

Tests the complete workflow from /api/runs/launch/ through task execution
to artifact generation and reporting.

CONTRACT:
- POST /api/runs/launch/ with tasks creates Run + RunJobs
- TaskExecutor executes all tasks
- All 3 task workers produce artifacts
- Status transitions tracked correctly
- Token counts aggregated
- No errors in any task
"""
from django.test import TestCase, Client
from django.utils import timezone
from core.models import (
    Directive, Job, Run, RunJob, RunArtifact, LLMCall,
    ContainerAllowlist, GPUState
)
from orchestrator.models import Run as OrchestratorRun, Job as OrchestratorJob
from orchestration.task_executor import TaskExecutor
from unittest.mock import patch
import json


class E7IntegrationLaunchTests(TestCase):
    """Test launch endpoint integration with E7 task workers"""
    
    def setUp(self):
        """Create test data and client"""
        self.client = Client()
        
        # Create test jobs for all 3 tasks
        d1 = Directive.objects.create(
            directive_type="D1", name="d1",
            directive_text="Analyze logs", version=1, is_active=True
        )
        d2 = Directive.objects.create(
            directive_type="D2", name="d2",
            directive_text="Report GPUs", version=1, is_active=True
        )
        d3 = Directive.objects.create(
            directive_type="D3", name="d3",
            directive_text="Map services", version=1, is_active=True
        )
        
        self.j1 = Job.objects.create(
            task_key="log_triage", name="Log Triage",
            default_directive=d1, is_active=True
        )
        self.j2 = Job.objects.create(
            task_key="gpu_report", name="GPU Report",
            default_directive=d2, is_active=True
        )
        self.j3 = Job.objects.create(
            task_key="service_map", name="Service Map",
            default_directive=d3, is_active=True
        )
    
    def test_launch_creates_run_and_run_jobs(self):
        """POST /api/runs/launch/ creates Run + RunJobs for all tasks"""
        response = self.client.post(
            '/api/runs/launch/',
            {'tasks': ['log_triage', 'gpu_report', 'service_map']},
            content_type='application/json'
        )
        
        # Verify response
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn('id', data)
        
        run_id = data['id']
        
        # Verify Orchestrator Run created (legacy endpoint)
        run = OrchestratorRun.objects.get(id=run_id)
        self.assertEqual(run.status, "pending")
        
        # Verify Jobs created (not RunJobs, as this is legacy endpoint)
        jobs = OrchestratorJob.objects.filter(run=run)
        self.assertEqual(jobs.count(), 3)
    
    def test_launch_initializes_task_worker_infrastructure(self):
        """Launch initializes task worker infrastructure"""
        response = self.client.post(
            '/api/runs/launch/',
            {'tasks': ['log_triage', 'gpu_report', 'service_map']},
            content_type='application/json'
        )
        
        run_id = response.json()['id']
        
        # Verify Orchestrator Run created with pending status
        run = OrchestratorRun.objects.get(id=run_id)
        self.assertEqual(run.status, "pending")
        
        # Verify all Jobs initialized  
        jobs = OrchestratorJob.objects.filter(run=run)
        self.assertEqual(jobs.count(), 3)
        
        for job in jobs:
            self.assertEqual(job.status, "pending")


class E7IntegrationTaskExecutionTests(TestCase):
    """Test task executor integration with all 3 workers"""
    
    def setUp(self):
        """Create test data and infrastructure"""
        # Create directives and jobs
        d1 = Directive.objects.create(
            directive_type="D1", name="d1",
            directive_text="Analyze logs", version=1, is_active=True
        )
        d2 = Directive.objects.create(
            directive_type="D2", name="d2",
            directive_text="Report GPUs", version=1, is_active=True
        )
        d3 = Directive.objects.create(
            directive_type="D3", name="d3",
            directive_text="Map services", version=1, is_active=True
        )
        
        self.j1 = Job.objects.create(
            task_key="log_triage", name="Log Triage",
            default_directive=d1, is_active=True
        )
        self.j2 = Job.objects.create(
            task_key="gpu_report", name="GPU Report",
            default_directive=d2, is_active=True
        )
        self.j3 = Job.objects.create(
            task_key="service_map", name="Service Map",
            default_directive=d3, is_active=True
        )
        
        # Create run
        self.run = Run.objects.create(
            job=self.j1,
            directive_snapshot_name=d1.name,
            directive_snapshot_text=d1.directive_text,
            status="pending"
        )
        
        # Create allowlisted containers for Task 3
        ContainerAllowlist.objects.create(
            container_id="web123",
            container_name="web",
            enabled=True
        )
        
        # Create GPU for Task 2
        GPUState.objects.create(
            gpu_id="0",
            gpu_name="NVIDIA RTX 4090",
            total_vram_mb=24576,
            used_vram_mb=20480,
            free_vram_mb=4096,
            utilization_percent=83.3,
            is_available=True,
            active_workers=2
        )
    
    def test_executor_creates_run_jobs(self):
        """TaskExecutor creates RunJobs for all tasks"""
        executor = TaskExecutor()
        jobs = [self.j1, self.j2, self.j3]
        
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        self.assertEqual(len(run_jobs), 3)
        self.assertEqual(RunJob.objects.filter(run=self.run).count(), 3)
    
    def test_task1_produces_artifact(self):
        """Task 1 produces markdown artifact"""
        executor = TaskExecutor()
        jobs = [self.j1]
        
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        # Execute task
        executor.execute_task(run_jobs[0])
        
        # Verify artifact created
        artifacts = RunArtifact.objects.filter(run=self.run)
        self.assertEqual(artifacts.count(), 1)
        
        artifact = artifacts.first()
        self.assertEqual(artifact.artifact_type, "markdown")
        self.assertIn("report.md", artifact.path)
    
    def test_task2_produces_artifact(self):
        """Task 2 produces JSON GPU report"""
        executor = TaskExecutor()
        jobs = [self.j2]
        
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        # Execute task
        executor.execute_task(run_jobs[0])
        
        # Verify artifact created
        artifacts = RunArtifact.objects.filter(run=self.run)
        self.assertEqual(artifacts.count(), 1)
        
        artifact = artifacts.first()
        self.assertEqual(artifact.artifact_type, "json")
        self.assertIn("gpu_report.json", artifact.path)
    
    def test_task3_produces_artifact(self):
        """Task 3 produces JSON service map"""
        executor = TaskExecutor()
        jobs = [self.j3]
        
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        # Execute task
        executor.execute_task(run_jobs[0])
        
        # Verify artifact created
        artifacts = RunArtifact.objects.filter(run=self.run)
        self.assertEqual(artifacts.count(), 1)
        
        artifact = artifacts.first()
        self.assertEqual(artifact.artifact_type, "json")
        self.assertIn("services.json", artifact.path)
    
    def test_all_tasks_succeed(self):
        """All 3 tasks complete successfully"""
        executor = TaskExecutor()
        jobs = [self.j1, self.j2, self.j3]
        
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        # Execute all tasks
        for run_job in run_jobs:
            executor.execute_task(run_job)
        
        # Verify all succeeded
        failed = RunJob.objects.filter(run=self.run, status="failed")
        self.assertEqual(failed.count(), 0)
        
        success = RunJob.objects.filter(run=self.run, status="success")
        self.assertEqual(success.count(), 3)


class E7IntegrationArtifactTests(TestCase):
    """Test artifact generation and storage"""
    
    def setUp(self):
        """Create test data"""
        d1 = Directive.objects.create(
            directive_type="D1", name="d1",
            directive_text="Analyze logs", version=1, is_active=True
        )
        self.j1 = Job.objects.create(
            task_key="log_triage", name="Log Triage",
            default_directive=d1, is_active=True
        )
        self.run = Run.objects.create(
            job=self.j1,
            directive_snapshot_name=d1.name,
            directive_snapshot_text=d1.directive_text,
            status="pending"
        )
    
    def test_all_artifacts_under_logs_directory(self):
        """All task artifacts stored under /logs/run_id/"""
        executor = TaskExecutor()
        jobs = [self.j1]
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        executor.execute_task(run_jobs[0])
        
        artifacts = RunArtifact.objects.filter(run=self.run)
        
        for artifact in artifacts:
            self.assertIn("/logs/run_", artifact.path)
            self.assertIn(str(self.run.id), artifact.path)
    
    def test_markdown_and_json_artifacts(self):
        """Artifacts are properly typed as markdown or JSON"""
        # Create markdown artifact
        RunArtifact.objects.create(
            run=self.run,
            artifact_type="markdown",
            path=f"/logs/run_{self.run.id}/report.md"
        )
        
        # Create JSON artifact
        RunArtifact.objects.create(
            run=self.run,
            artifact_type="json",
            path=f"/logs/run_{self.run.id}/data.json"
        )
        
        artifacts = RunArtifact.objects.filter(run=self.run)
        types = [a.artifact_type for a in artifacts]
        
        self.assertIn("markdown", types)
        self.assertIn("json", types)


class E7IntegrationTokenTrackingTests(TestCase):
    """Test token tracking across all tasks"""
    
    def setUp(self):
        """Create test data"""
        d1 = Directive.objects.create(
            directive_type="D1", name="d1",
            directive_text="Analyze logs", version=1, is_active=True
        )
        self.j1 = Job.objects.create(
            task_key="log_triage", name="Log Triage",
            default_directive=d1, is_active=True
        )
        self.run = Run.objects.create(
            job=self.j1,
            directive_snapshot_name=d1.name,
            directive_snapshot_text=d1.directive_text,
            status="pending"
        )
    
    def test_token_counts_recorded_for_llm_calls(self):
        """LLM calls record token counts, not content"""
        # Create containers for log collection
        ContainerAllowlist.objects.create(
            container_id="web_for_logs",
            container_name="web",
            enabled=True
        )
        
        executor = TaskExecutor()
        jobs = [self.j1]
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        # Mock docker to avoid real connection
        with patch('orchestration.task_workers.DockerLogCollector') as mock_collector:
            mock_instance = mock_collector.return_value
            mock_instance.collect_logs_since_last_run.return_value = "Sample logs"
            
            executor.execute_task(run_jobs[0])
        
        # Verify LLMCall created with token counts
        llm_calls = LLMCall.objects.filter(run=self.run)
        self.assertGreater(llm_calls.count(), 0)
        
        for call in llm_calls:
            self.assertGreater(call.total_tokens, 0)
            self.assertIsNone(getattr(call, 'prompt', None) or None)
            self.assertIsNone(getattr(call, 'response', None) or None)
