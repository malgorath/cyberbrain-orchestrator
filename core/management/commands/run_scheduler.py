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

from core.models import Schedule, ScheduledRun
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

                # Check if this schedule already has a ScheduledRun (from launch API)
                existing_scheduled_run = ScheduledRun.objects.filter(
                    schedule=sch,
                    status__in=['pending']
                ).select_related('run').first()

                if existing_scheduled_run:
                    # Launched run: execute only the specific job for this schedule
                    # Parse task_type from schedule name: "launch-run-{run_id}-{task_type}"
                    legacy_run = existing_scheduled_run.run
                    task_type = self._extract_task_type_from_schedule(sch)
                    
                    if not task_type:
                        logger.error(f"Cannot parse task_type from schedule {sch.id} ({sch.name})")
                        existing_scheduled_run.status = 'failed'
                        existing_scheduled_run.finished_at = now
                        existing_scheduled_run.error_summary = 'Invalid schedule name format'
                        existing_scheduled_run.save()
                        sch.enabled = False
                        sch.save(update_fields=['enabled'])
                        continue
                    
                    # Find the specific job for this task_type
                    target_job = LegacyJob.objects.filter(
                        run=legacy_run,
                        task_type=task_type
                    ).first()
                    
                    if not target_job:
                        logger.error(f"Job {task_type} not found for run {legacy_run.id}")
                        existing_scheduled_run.status = 'failed'
                        existing_scheduled_run.finished_at = now
                        existing_scheduled_run.error_summary = f'Job {task_type} not found'
                        existing_scheduled_run.save()
                        sch.enabled = False
                        sch.save(update_fields=['enabled'])
                        continue
                    
                    # Check if job already completed/failed (prevent duplicate execution)
                    if target_job.status in ['completed', 'failed']:
                        logger.info(f"Job {target_job.id} ({task_type}) already {target_job.status}, skipping")
                        existing_scheduled_run.status = 'finished'
                        existing_scheduled_run.finished_at = now
                        existing_scheduled_run.save()
                        sch.enabled = False
                        sch.save(update_fields=['enabled'])
                        continue
                    
                    logger.info(f"Executing job {target_job.id} ({task_type}) for run {legacy_run.id}")
                    existing_scheduled_run.status = 'started'
                    existing_scheduled_run.started_at = now
                    existing_scheduled_run.save(update_fields=['status', 'started_at'])
                else:
                    # Concurrency checks for recurring schedules
                    if not self._can_run(sch):
                        # Push next run out by small backoff to avoid tight loop
                        sch.next_run_at = now + timedelta(minutes=1)
                        # Release claim immediately
                        sch.claimed_by = ''
                        sch.claimed_until = None
                        sch.save(update_fields=['next_run_at', 'claimed_by', 'claimed_until'])
                        continue

                    # Recurring schedule: create new run
                    legacy_directive = self._resolve_directive(sch)
                    legacy_run = LegacyRun.objects.create(directive=legacy_directive, status='pending')
                    LegacyJob.objects.create(run=legacy_run, task_type=sch.job.task_key, status='pending')

                    # Link scheduled history
                    existing_scheduled_run = ScheduledRun.objects.create(
                        schedule=sch,
                        run=legacy_run,
                        status='started',
                        started_at=now
                    )

                # Disable schedule after execution (one-shot queue item)
                sch.enabled = False
                sch.last_run_at = now
                sch.save(update_fields=['enabled', 'last_run_at'])

                # Execute job or run
                try:
                    if existing_scheduled_run and task_type:
                        # Execute single job
                        logger.info(f"Executing job {target_job.id} ({task_type}) for schedule {sch.id}")
                        ok = orchestrator.execute_job(target_job)
                        logger.info(f"Job {target_job.id} execution {'succeeded' if ok else 'failed'}")
                        
                        # Update run status based on all jobs
                        self._update_run_status(legacy_run)
                        
                        if existing_scheduled_run:
                            existing_scheduled_run.status = 'finished' if ok else 'failed'
                            existing_scheduled_run.finished_at = timezone.now()
                            if not ok:
                                existing_scheduled_run.error_summary = target_job.error_message or 'Job failed'
                            existing_scheduled_run.save()
                    else:
                        # Execute entire run (recurring schedules)
                        logger.info(f"Executing run {legacy_run.id} for schedule {sch.id} ({sch.name})")
                        ok = orchestrator.execute_run(legacy_run)
                        logger.info(f"Run {legacy_run.id} execution {'succeeded' if ok else 'failed'}")
                        if existing_scheduled_run:
                            existing_scheduled_run.status = 'finished' if ok else 'failed'
                            existing_scheduled_run.finished_at = timezone.now()
                            if not ok:
                                existing_scheduled_run.error_summary = legacy_run.error_message or 'Run failed'
                            existing_scheduled_run.save()
                except Exception as e:
                    logger.error(f"Run execution error for schedule {sch.id}: {e}", exc_info=True)
                    if existing_scheduled_run:
                        existing_scheduled_run.status = 'failed'
                        existing_scheduled_run.finished_at = timezone.now()
                        existing_scheduled_run.error_summary = str(e)
                        existing_scheduled_run.save()

                # Release claim now that scheduling work is complete
                sch.claimed_by = ''
                sch.claimed_until = None
                sch.save(update_fields=['claimed_by', 'claimed_until'])

    def _resolve_directive(self, sch: Schedule):
        # Prefer core directive mapped by name; otherwise derive from schedule
        name = sch.directive.name if sch.directive else f"schedule:{sch.name}"
        desc = (sch.directive.description if sch.directive else sch.custom_directive_text[:500]) or ''
        defaults = {'description': desc, 'task_config': sch.directive.task_config if sch.directive else {}}
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
    
    def _extract_task_type_from_schedule(self, sch: Schedule) -> str:
        """Extract task_type from schedule name (format: launch-run-{id}-{task_type})."""
        if not sch.name.startswith('launch-run-'):
            return None
        parts = sch.name.split('-', 3)  # ['launch', 'run', '{id}', '{task_type}']
        if len(parts) >= 4:
            return parts[3]
        return None
    
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
