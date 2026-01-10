"""
Acceptance tests for the execution pipeline:
Launch → Schedule Creation → Scheduler Execution → Job State Transitions

Test Contract:
- POST /api/runs/launch/ creates Run, Jobs, and Schedules
- Schedules are due immediately (next_run_at <= now)
- ScheduledRun links Schedule → Run before execution
- Scheduler claims schedules and executes existing runs
- Job state transitions: pending → running → completed/failed
- Run state transitions based on all jobs completion
"""
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient

from orchestrator.models import Directive, Run as LegacyRun, Job as LegacyJob
from core.models import Job as CoreJob, Schedule, ScheduledRun, WorkerHost
from core.management.commands.run_scheduler import Command as SchedulerCommand
from orchestrator.services import OrchestratorService


class ExecutionPipelineTests(TestCase):
    """Test the complete execution pipeline from launch to job completion."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.directive = Directive.objects.create(
            name='test-directive',
            description='Test directive for execution pipeline'
        )
        
        # Create a worker host
        self.host = WorkerHost.objects.create(
            name='test-host',
            docker_socket_path='/var/run/docker.sock',
            enabled=True,
            healthy=True
        )

    def test_launch_creates_schedules(self):
        """
        ATDD: Launch creates Schedule entries for each task.
        
        Contract:
        - POST /api/runs/launch/ with tasks=['log_triage', 'gpu_report']
        - Creates 2 Schedule entries with unique names
        - All schedules have next_run_at <= now (due immediately)
        - ScheduledRun entries link Schedule → Run with status='pending'
        """
        response = self.client.post('/api/runs/launch/', {
            'directive_id': self.directive.id,
            'tasks': ['log_triage', 'gpu_report']
        }, format='json')
        
        self.assertEqual(response.status_code, 201)
        run_id = response.data['id']
        
        # Assert: 2 schedules created
        schedules = Schedule.objects.filter(name__startswith=f'launch-run-{run_id}')
        self.assertEqual(schedules.count(), 2)
        
        # Assert: All schedules due immediately
        now = timezone.now()
        for schedule in schedules:
            self.assertIsNotNone(schedule.next_run_at)
            self.assertLessEqual(schedule.next_run_at, now)
            self.assertTrue(schedule.enabled)
        
        # Assert: ScheduledRun entries exist with status='pending'
        scheduled_runs = ScheduledRun.objects.filter(schedule__in=schedules)
        self.assertEqual(scheduled_runs.count(), 2)
        for sr in scheduled_runs:
            self.assertEqual(sr.status, 'pending')
            self.assertEqual(sr.run.id, run_id)

    def test_scheduler_executes_launched_run(self):
        """
        ATDD: Scheduler detects launched run and executes it.
        
        Contract:
        - Scheduler._tick() finds due schedules
        - Detects existing ScheduledRun (from launch)
        - Uses existing Run instead of creating new one
        - Calls orchestrator.execute_run()
        - Updates ScheduledRun.status from 'pending' → 'started' → 'finished'
        """
        # Create run + jobs + schedules (simulating launch)
        run = LegacyRun.objects.create(
            directive=self.directive,
            status='pending',
            worker_host=self.host
        )
        LegacyJob.objects.create(run=run, task_type='log_triage', status='pending')
        
        core_job, _ = CoreJob.objects.get_or_create(
            task_key='log_triage',
            defaults={'name': 'Log Triage', 'is_active': True}
        )
        
        schedule = Schedule.objects.create(
            name=f'launch-run-{run.id}-log_triage',
            job=core_job,
            schedule_type='interval',
            interval_minutes=999999,
            next_run_at=timezone.now(),
            enabled=True
        )
        
        scheduled_run = ScheduledRun.objects.create(
            schedule=schedule,
            run=run,
            status='pending'
        )
        
        # Mock OrchestratorService.execute_run
        with patch.object(OrchestratorService, 'execute_run', return_value=True) as mock_execute:
            # Execute scheduler tick
            cmd = SchedulerCommand()
            orchestrator = OrchestratorService()
            cmd._tick(orchestrator, max_claim=10, claim_ttl=120, claimant='test-scheduler')
        
        # Assert: execute_run was called with the existing run
        mock_execute.assert_called_once()
        called_run = mock_execute.call_args[0][0]
        self.assertEqual(called_run.id, run.id)
        
        # Assert: ScheduledRun status updated to 'finished'
        scheduled_run.refresh_from_db()
        self.assertEqual(scheduled_run.status, 'finished')
        self.assertIsNotNone(scheduled_run.started_at)
        self.assertIsNotNone(scheduled_run.finished_at)

    def test_job_state_transitions_during_execution(self):
        """
        ATDD: Jobs transition through states during execution.
        
        Contract:
        - Job starts with status='pending'
        - execute_job() sets status='running', started_at
        - On success: status='completed', completed_at
        - On failure: status='failed', error_message
        """
        run = LegacyRun.objects.create(
            directive=self.directive,
            status='pending',
            worker_host=self.host
        )
        job = LegacyJob.objects.create(run=run, task_type='log_triage', status='pending')
        
        # Mock task handler to succeed
        with patch.object(OrchestratorService, 'execute_log_triage', return_value=True):
            service = OrchestratorService()
            success = service.execute_job(job)
        
        # Assert: Job completed successfully
        self.assertTrue(success)
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.completed_at)

    def test_run_status_reflects_all_jobs_completion(self):
        """
        ATDD: Run status aggregates job states.
        
        Contract:
        - Run status='running' when any job is running
        - Run status='completed' when all jobs succeed
        - Run status='failed' if any job fails
        """
        run = LegacyRun.objects.create(
            directive=self.directive,
            status='pending',
            worker_host=self.host
        )
        LegacyJob.objects.create(run=run, task_type='log_triage', status='pending')
        LegacyJob.objects.create(run=run, task_type='gpu_report', status='pending')
        
        # Mock both tasks to succeed
        with patch.object(OrchestratorService, 'execute_log_triage', return_value=True), \
             patch.object(OrchestratorService, 'execute_gpu_report', return_value=True):
            service = OrchestratorService()
            success = service.execute_run(run)
        
        # Assert: Run completed successfully
        self.assertTrue(success)
        run.refresh_from_db()
        self.assertEqual(run.status, 'completed')
        self.assertIsNotNone(run.completed_at)
        
        # Assert: All jobs completed
        for job in run.jobs.all():
            self.assertEqual(job.status, 'completed')

    def test_scheduler_skips_recurring_schedules_with_concurrency_limits(self):
        """
        ATDD: Scheduler respects concurrency limits for recurring schedules.
        
        Contract (negative path):
        - Recurring schedule (no existing ScheduledRun) checks concurrency
        - If max_global/max_per_job exceeded, schedule is deferred
        - Claimed schedule is released immediately
        """
        # Create recurring schedule without existing ScheduledRun
        core_job, _ = CoreJob.objects.get_or_create(
            task_key='log_triage',
            defaults={'name': 'Log Triage', 'is_active': True}
        )
        
        schedule = Schedule.objects.create(
            name='recurring-log-triage',
            job=core_job,
            schedule_type='interval',
            interval_minutes=10,
            next_run_at=timezone.now(),
            enabled=True,
            max_global=0  # No runs allowed
        )
        
        # Execute scheduler tick
        cmd = SchedulerCommand()
        orchestrator = OrchestratorService()
        
        with patch.object(OrchestratorService, 'execute_run', return_value=True) as mock_execute:
            cmd._tick(orchestrator, max_claim=10, claim_ttl=120, claimant='test-scheduler')
        
        # Assert: execute_run was NOT called (concurrency limit)
        mock_execute.assert_not_called()
        
        # Assert: Schedule deferred
        schedule.refresh_from_db()
        self.assertIsNotNone(schedule.next_run_at)
        self.assertEqual(schedule.claimed_by, '')  # Released

    def test_end_to_end_launch_to_completion(self):
        """
        ATDD: Full pipeline from launch to completion.
        
        Contract:
        1. POST /api/runs/launch/
        2. Creates Run, Jobs, Schedules, ScheduledRuns
        3. Scheduler claims schedules
        4. Executes jobs (mocked)
        5. Run and Jobs transition to 'completed'
        """
        # Step 1: Launch run
        response = self.client.post('/api/runs/launch/', {
            'directive_id': self.directive.id,
            'tasks': ['log_triage']
        }, format='json')
        
        self.assertEqual(response.status_code, 201)
        run_id = response.data['id']
        
        # Step 2: Verify setup
        run = LegacyRun.objects.get(id=run_id)
        self.assertEqual(run.status, 'pending')
        self.assertEqual(run.jobs.count(), 1)
        
        schedules = Schedule.objects.filter(name__startswith=f'launch-run-{run_id}')
        self.assertEqual(schedules.count(), 1)
        
        # Step 3: Scheduler executes (with mocked task)
        with patch.object(OrchestratorService, 'execute_log_triage', return_value=True):
            cmd = SchedulerCommand()
            orchestrator = OrchestratorService()
            cmd._tick(orchestrator, max_claim=10, claim_ttl=120, claimant='test-scheduler')
        
        # Step 4: Verify completion
        run.refresh_from_db()
        self.assertEqual(run.status, 'completed')
        
        job = run.jobs.first()
        self.assertEqual(job.status, 'completed')
        
        # Step 5: Verify ScheduledRun status
        scheduled_run = ScheduledRun.objects.filter(run=run).first()
        self.assertEqual(scheduled_run.status, 'finished')
