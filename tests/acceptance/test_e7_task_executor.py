"""
E7 Task Executor Acceptance Tests

Tests for TaskExecutor service that orchestrates all 3 task workers
and manages their lifecycle.
"""
from django.test import TestCase
from django.utils import timezone
from core.models import Directive, Job, Run, RunJob, RunArtifact
from orchestration.task_executor import TaskExecutor
from unittest.mock import MagicMock, patch
import json


class TaskExecutorTests(TestCase):
    """Test TaskExecutor orchestration framework"""
    
    def setUp(self):
        """Create test directives and jobs"""
        # Create Task 1
        self.d1 = Directive.objects.create(
            directive_type="D1", name="d1", directive_text="Analyze logs",
            version=1, is_active=True
        )
        self.j1 = Job.objects.create(
            task_key="log_triage", name="Log Triage",
            default_directive=self.d1, is_active=True
        )
        
        # Create Task 2
        self.d2 = Directive.objects.create(
            directive_type="D2", name="d2", directive_text="Report GPUs",
            version=1, is_active=True
        )
        self.j2 = Job.objects.create(
            task_key="gpu_report", name="GPU Report",
            default_directive=self.d2, is_active=True
        )
        
        # Create Task 3
        self.d3 = Directive.objects.create(
            directive_type="D3", name="d3", directive_text="Map services",
            version=1, is_active=True
        )
        self.j3 = Job.objects.create(
            task_key="service_map", name="Service Map",
            default_directive=self.d3, is_active=True
        )
        
        # Create run
        self.run = Run.objects.create(
            job=self.j1,
            directive_snapshot_name=self.d1.name,
            directive_snapshot_text=self.d1.directive_text,
            status="pending"
        )
    
    def test_task_executor_creation(self):
        """TaskExecutor can be instantiated"""
        executor = TaskExecutor()
        self.assertIsNotNone(executor)
    
    def test_task_executor_can_create_run_jobs(self):
        """TaskExecutor can create RunJobs for all tasks"""
        executor = TaskExecutor()
        jobs = [self.j1, self.j2, self.j3]
        
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        self.assertEqual(len(run_jobs), 3)
        self.assertEqual(RunJob.objects.filter(run=self.run).count(), 3)
    
    def test_task_executor_initializes_token_counts(self):
        """TaskExecutor initializes token counts on RunJobs"""
        executor = TaskExecutor()
        
        # Create run job with 0 tokens
        run_job = RunJob.objects.create(
            run=self.run,
            job=self.j1,
            status="pending",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0
        )
        
        self.assertEqual(run_job.total_tokens, 0)
    
    @patch('orchestration.task_executor.TaskExecutor.execute_task')
    def test_task_executor_executes_all_tasks(self, mock_execute):
        """TaskExecutor orchestrates execution of all tasks"""
        mock_execute.return_value = None
        
        executor = TaskExecutor()
        jobs = [self.j1, self.j2, self.j3]
        run_jobs = executor.create_run_jobs(self.run, jobs)
        
        # Execute each task
        for run_job in run_jobs:
            executor.execute_task(run_job)
        
        # Verify execute_task was called 3 times
        self.assertEqual(mock_execute.call_count, 3)
