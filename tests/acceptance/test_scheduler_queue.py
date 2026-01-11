from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from core.models import Schedule, Job as CoreJob, Directive as CoreDirective, JobQueueItem
from orchestrator.models import Run as LegacyRun, Job as LegacyJob


class FakeOrchestratorService:
    def execute_job(self, job):
        job.status = 'completed'
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])
        return True


class SchedulerQueueAcceptanceTests(TestCase):
    def setUp(self):
        self.directive = CoreDirective.objects.create(
            directive_type='D1',
            name='D1 Default',
            description='Default D1 directive',
            is_builtin=True,
        )
        self.task = CoreJob.objects.create(
            task_key='log_triage',
            name='Log Triage',
            default_directive=self.directive,
            is_active=True,
        )

    def test_due_schedule_creates_run_once_and_executes_job_once(self):
        schedule = Schedule.objects.create(
            name='one-shot-triage',
            job=self.task,
            enabled=True,
            schedule_type='one_shot',
            next_run_at=timezone.now() - timedelta(minutes=1),
            timezone='UTC',
        )

        from core.management.commands.run_scheduler import Command as SchedulerCommand
        cmd = SchedulerCommand()
        cmd._tick(FakeOrchestratorService(), max_claim=5, claim_ttl=60, claimant='test-scheduler')

        self.assertEqual(LegacyRun.objects.count(), 1)
        self.assertEqual(LegacyJob.objects.count(), 1)
        self.assertEqual(JobQueueItem.objects.count(), 1)
        queue_item = JobQueueItem.objects.first()
        self.assertEqual(queue_item.status, 'completed')
        schedule.refresh_from_db()
        self.assertFalse(schedule.enabled)

        cmd._tick(FakeOrchestratorService(), max_claim=5, claim_ttl=60, claimant='test-scheduler')
        self.assertEqual(LegacyRun.objects.count(), 1)
        self.assertEqual(JobQueueItem.objects.count(), 1)
