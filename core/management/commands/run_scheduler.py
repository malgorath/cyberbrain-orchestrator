"""
Phase 2 Scheduler: Polls Postgres for due schedules and launches runs.
Usage: python manage.py run_scheduler
Supports TTL-based claiming to ensure crash-safety and multi-instance correctness.
"""
import time
import logging
import os
import socket
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Schedule, ScheduledRun, JobQueueItem
from orchestrator.models import Run as LegacyRun, Job as LegacyJob, Directive as LegacyDirective
from orchestrator.services import OrchestratorService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the Phase 2 scheduler loop to trigger scheduled jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=30, help='Polling interval seconds')
        parser.add_argument('--max-claim', type=int, default=10, help='Max schedules to claim per tick')
        parser.add_argument('--claim-ttl', type=int, default=120, help='Seconds to hold a schedule claim (crash-safety TTL)')
        parser.add_argument('--claimant', type=str, default='', help='Identifier for this scheduler instance (defaults to hostname:pid)')

    def handle(self, *args, **options):
        poll_interval = options.get('interval', 30)
        max_claim = options.get('max_claim', 10)
        # Django argparse maps '--claim-ttl' -> 'claim_ttl'
        claim_ttl = options.get('claim_ttl', 120)
        claimant = options.get('claimant') or f"{socket.gethostname()}:{os.getpid()}"
        self.stdout.write(self.style.SUCCESS(f'Scheduler starting (interval={poll_interval}s)...'))

        orchestrator = OrchestratorService()

        while True:
            try:
                self._tick(orchestrator, max_claim, claim_ttl, claimant)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('Scheduler stopped by user'))
                break
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}")
            time.sleep(poll_interval)

    def _tick(self, orchestrator: OrchestratorService, max_claim: int, claim_ttl: int, claimant: str):
        now = timezone.now()
        logger.info(f"Scheduler tick at {now.isoformat()} (claimant={claimant})")
        
        # Heartbeat: refresh all enabled WorkerHosts to prevent staleness
        from core.models import WorkerHost
        enabled_hosts = WorkerHost.objects.filter(enabled=True)
        for host in enabled_hosts:
            host.last_seen_at = now
            host.save(update_fields=['last_seen_at'])
        logger.info(f"Heartbeat: refreshed {enabled_hosts.count()} enabled host(s)")
        
        # Claim due schedules with row locks to prevent double-run
        with transaction.atomic():
            due_qs = Schedule.due().select_for_update(skip_locked=True)[:max_claim]
            schedules = list(due_qs)
            
            if schedules:
                logger.info(f"Claimed {len(schedules)} due schedule(s): {[s.name for s in schedules]}")
            else:
                logger.info("No due schedules found")

            for sch in schedules:
                # Acquire claim with TTL to ensure crash-safety and multi-instance correctness
                sch.claimed_by = claimant
                sch.claimed_until = now + timedelta(seconds=claim_ttl)
                sch.save(update_fields=['claimed_by', 'claimed_until'])

                # Concurrency checks for recurring schedules
                if not self._can_run(sch):
                    # Push next run out by small backoff to avoid tight loop
                    sch.next_run_at = now + timedelta(minutes=1)
                    # Release claim immediately
                    sch.claimed_by = ''
                    sch.claimed_until = None
                    sch.save(update_fields=['next_run_at', 'claimed_by', 'claimed_until'])
                    continue

                if not sch.job.is_active:
                    sch.enabled = False
                    sch.claimed_by = ''
                    sch.claimed_until = None
                    sch.save(update_fields=['enabled', 'claimed_by', 'claimed_until'])
                    continue

                # Create run + job + queue item
                legacy_directive = self._resolve_directive(sch)
                legacy_run = LegacyRun.objects.create(
                    directive=legacy_directive,
                    status='pending',
                    directive_snapshot={
                        'id': legacy_directive.id,
                        'name': legacy_directive.name,
                        'description': legacy_directive.description,
                        'task_config': legacy_directive.task_config,
                    }
                )
                legacy_job = LegacyJob.objects.create(
                    run=legacy_run,
                    task_type=sch.job.task_key,
                    status='pending'
                )
                JobQueueItem.objects.create(job=legacy_job, run=legacy_run)

                # Link scheduled history
                ScheduledRun.objects.create(
                    schedule=sch,
                    run=legacy_run,
                    status='pending'
                )

                # Update schedule for next run
                sch.last_run_at = now
                if sch.schedule_type == 'one_shot':
                    sch.enabled = False
                    sch.next_run_at = None
                else:
                    sch.compute_next_run(from_time=now)

                # Release claim now that scheduling work is complete
                sch.claimed_by = ''
                sch.claimed_until = None
                sch.save(update_fields=['enabled', 'last_run_at', 'next_run_at', 'claimed_by', 'claimed_until'])

        # Process due job queue items
        queue_items = []
        with transaction.atomic():
            due_items = JobQueueItem.due().select_for_update(skip_locked=True)[:max_claim]
            queue_items = list(due_items)
            for item in queue_items:
                item.status = 'claimed'
                item.attempts += 1
                item.claimed_by = claimant
                item.claimed_until = now + timedelta(seconds=claim_ttl)
                item.save(update_fields=['status', 'attempts', 'claimed_by', 'claimed_until'])

        for item in queue_items:
            job = item.job
            run = item.run

            if job.status in ['completed', 'failed']:
                item.status = 'completed'
                item.claimed_by = ''
                item.claimed_until = None
                item.save(update_fields=['status', 'claimed_by', 'claimed_until'])
                continue

            try:
                if run.status == 'pending':
                    run.status = 'running'
                    run.save(update_fields=['status'])

                item.status = 'running'
                item.save(update_fields=['status'])
                ok = orchestrator.execute_job(job)
                item.status = 'completed' if ok else 'failed'
                item.last_error = job.error_message if not ok else ''
                item.claimed_by = ''
                item.claimed_until = None
                item.save(update_fields=['status', 'last_error', 'claimed_by', 'claimed_until'])
                self._update_run_status(run)
            except Exception as e:
                logger.error(f"Job execution error for queue item {item.id}: {e}", exc_info=True)
                item.status = 'failed'
                item.last_error = str(e)
                item.claimed_by = ''
                item.claimed_until = None
                item.save(update_fields=['status', 'last_error', 'claimed_by', 'claimed_until'])
                self._update_run_status(run)

    def _resolve_directive(self, sch: Schedule):
        # Prefer core directive mapped by name; otherwise derive from schedule
        core_directive = sch.directive or sch.job.default_directive
        name = core_directive.name if core_directive else f"schedule:{sch.name}"
        desc = (core_directive.description if core_directive else sch.custom_directive_text[:500]) or ''
        defaults = {'description': desc, 'task_config': core_directive.task_config if core_directive else {}}
        directive, _ = LegacyDirective.objects.get_or_create(name=name, defaults=defaults)
        return directive

    def _can_run(self, sch: Schedule) -> bool:
        """Enforce max_global and max_per_job concurrency limits."""
        # Global running runs count
        global_running = LegacyRun.objects.filter(status='running').count()
        if sch.max_global is not None and global_running >= sch.max_global:
            return False
        # Job-specific running jobs count
        job_running = LegacyJob.objects.filter(task_type=sch.job.task_key, status='running').count()
        if sch.max_per_job is not None and job_running >= sch.max_per_job:
            return False
        return True
    
    def _update_run_status(self, run: LegacyRun):
        """Update run status based on all jobs' statuses."""
        jobs = run.jobs.all()
        if not jobs:
            return
        
        statuses = [j.status for j in jobs]
        
        # If any job is running, run is running
        if 'running' in statuses:
            if run.status != 'running':
                run.status = 'running'
                run.save(update_fields=['status'])
            return
        
        # If any job is pending, run stays pending or running
        if 'pending' in statuses:
            if run.status not in ['pending', 'running']:
                run.status = 'pending'
                run.save(update_fields=['status'])
            return
        
        # All jobs are completed or failed
        if 'failed' in statuses:
            if run.status != 'failed':
                run.status = 'failed'
                run.completed_at = timezone.now()
                run.save(update_fields=['status', 'completed_at'])
        else:
            # All completed
            if run.status != 'completed':
                run.status = 'completed'
                run.completed_at = timezone.now()
                run.save(update_fields=['status', 'completed_at'])
