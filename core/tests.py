from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command

from .models import (
	Directive,
	Job,
	Run,
	RunArtifact,
	LLMCall,
	ContainerInventory,
	ContainerAllowlist,
    Schedule,
)
from orchestrator.models import Run as LegacyRun, Job as LegacyJob, Directive as LegacyDirective



class CoreModelSmokeTests(TestCase):
	def setUp(self):
		self.directive = Directive.objects.create(
			directive_type='D1',
			name='D1 - Log Triage',
			description='Builtin log triage directive',
			directive_text='Analyze logs for errors',
			is_builtin=True,
		)
		self.job = Job.objects.create(
			task_key='log_triage',
			name='Log triage job',
			default_directive=self.directive,
			config={'since_last_successful_run': True},
		)

	def test_run_and_artifacts_and_llm_calls(self):
		run = Run.objects.create(
			job=self.job,
			directive_snapshot_name=self.directive.name,
			directive_snapshot_text='custom override',
			status='pending',
		)

		artifact = RunArtifact.objects.create(
			run=run,
			artifact_type='markdown',
			path='runs/1/report.md',
			file_size_bytes=1024,
			mime_type='text/markdown',
		)

		llm_call = LLMCall.objects.create(
			run=run,
			worker_id='worker-1',
			endpoint='vllm',
			model_id='llama-3',
			prompt_tokens=10,
			completion_tokens=20,
			total_tokens=30,
			duration_ms=1200,
		)

		self.assertEqual(Run.objects.count(), 1)
		self.assertEqual(RunArtifact.objects.count(), 1)
		self.assertEqual(LLMCall.objects.count(), 1)
		self.assertEqual(artifact.path, 'runs/1/report.md')
		self.assertEqual(llm_call.total_tokens, 30)

	def test_since_last_successful_run(self):
		Run.objects.create(
			job=self.job,
			directive_snapshot_name=self.directive.name,
			directive_snapshot_text='snapshot',
			status='success',
			started_at=timezone.now() - timezone.timedelta(hours=1),
			ended_at=timezone.now() - timezone.timedelta(minutes=30),
		)

		latest = Run.get_last_successful_run()
		self.assertIsNotNone(latest)
		self.assertEqual(latest.status, 'success')

	def test_container_allowlist_and_inventory(self):
		allow = ContainerAllowlist.objects.create(
			container_id='abc123',
			container_name='web',
			enabled=True,
			description='Example container',
		)

		snapshot = ContainerInventory.objects.create(
			container_id='abc123',
			container_name='web',
			snapshot_data={'status': 'running'},
		)

		self.assertTrue(allow.enabled)
		self.assertEqual(snapshot.snapshot_data['status'], 'running')


	class ScheduleUnitTests(TestCase):
		def setUp(self):
			self.directive = Directive.objects.create(
				directive_type='D2', name='D2 - GPU', description='GPU directive', is_builtin=True
			)
			self.job = Job.objects.create(task_key='gpu_report', name='GPU report')

		def test_interval_next_run(self):
			sch = Schedule.objects.create(
				name='gpu-every-10', job=self.job, directive=self.directive,
				enabled=True, schedule_type='interval', interval_minutes=10, timezone='UTC'
			)
			nxt = sch.compute_next_run()
			self.assertIsNotNone(nxt)
			self.assertIsNotNone(sch.next_run_at)

		def test_cron_next_run(self):
			sch = Schedule.objects.create(
				name='gpu-nightly', job=self.job, directive=self.directive,
				enabled=True, schedule_type='cron', cron_expr='0 2 * * *', timezone='UTC'
			)
			nxt = sch.compute_next_run()
			self.assertIsNotNone(nxt)
			self.assertIsNotNone(sch.next_run_at)

		def test_concurrency_enforcement(self):
			# Prepare legacy directive and a running job of same type
			leg_dir, _ = LegacyDirective.objects.get_or_create(name='default', defaults={'description': 'Default'})
			leg_run = LegacyRun.objects.create(directive=leg_dir, status='running')
			LegacyJob.objects.create(run=leg_run, task_type='gpu_report', status='running')

			# Schedule due now with max_per_job=1 (already at limit)
			sch = Schedule.objects.create(
				name='gpu-concurrency', job=self.job, directive=self.directive,
				enabled=True, schedule_type='interval', interval_minutes=1, timezone='UTC',
				max_per_job=1, next_run_at=timezone.now()
			)

			# Run a single scheduler tick; expect no new LegacyRun created
			before_runs = LegacyRun.objects.count()
			# Import and run a single scheduler tick
			from core.management.commands.run_scheduler import Command as SchedulerCommand
			from orchestrator.services import OrchestratorService
			cmd = SchedulerCommand()
			cmd._tick(OrchestratorService(), max_claim=5, claim_ttl=60, claimant='test-scheduler-A')
			after_runs = LegacyRun.objects.count()
			self.assertEqual(before_runs, after_runs)

		def test_claim_ttl_respected(self):
			# Create a schedule due now
			sch = Schedule.objects.create(
				name='gpu-claim-ttl', job=self.job, directive=self.directive,
				enabled=True, schedule_type='interval', interval_minutes=1, timezone='UTC',
				next_run_at=timezone.now()
			)
			# Simulate an active claim held by another scheduler
			sch.claimed_by = 'scheduler-A'
			sch.claimed_until = timezone.now() + timedelta(seconds=120)
			sch.save(update_fields=['claimed_by', 'claimed_until'])

			# Run tick with a different claimant; should not schedule due to active claim
			before_runs = LegacyRun.objects.count()
			from core.management.commands.run_scheduler import Command as SchedulerCommand
			from orchestrator.services import OrchestratorService
			cmd = SchedulerCommand()
			cmd._tick(OrchestratorService(), max_claim=5, claim_ttl=60, claimant='scheduler-B')
			after_runs = LegacyRun.objects.count()
			self.assertEqual(before_runs, after_runs)

			# Expire the claim and retry; now it should schedule
			sch.claimed_until = timezone.now() - timedelta(seconds=1)
			sch.save(update_fields=['claimed_until'])
			cmd._tick(OrchestratorService(), max_claim=5, claim_ttl=60, claimant='scheduler-B')
			after_runs_2 = LegacyRun.objects.count()
			self.assertEqual(after_runs_2, before_runs + 1)
