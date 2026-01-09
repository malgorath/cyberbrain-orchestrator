"""
Phase 5: Agent Executor Management Command

Background worker that polls for pending agent runs and executes them.
Crash-safe claiming with TTL for multi-instance support.
"""

import logging
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from core.models import AgentRun
from orchestrator.agent.executor import AgentExecutor


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the agent executor worker loop"
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Poll interval in seconds (default: 5)'
        )
        parser.add_argument(
            '--ttl',
            type=int,
            default=300,
            help='Claim TTL in seconds (default: 300, prevents zombie claims)'
        )
    
    def handle(self, *args, **options):
        interval = options['interval']
        ttl_seconds = options['ttl']
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Agent executor started (interval={interval}s, ttl={ttl_seconds}s)"
            )
        )
        
        executor = AgentExecutor()
        
        try:
            while True:
                try:
                    self._tick(executor, ttl_seconds)
                except Exception as e:
                    logger.exception(f"Executor tick error: {e}")
                
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nAgent executor stopped"))
    
    def _tick(self, executor: AgentExecutor, ttl_seconds: int) -> None:
        """
        Single executor loop iteration.
        
        Claims pending/approval-pending agent runs and executes them.
        TTL prevents zombie claims if a previous worker crashed.
        """
        now = timezone.now()
        claimed_until = now + timedelta(seconds=ttl_seconds)
        
        # Find agent runs ready to execute
        pending_runs = AgentRun.objects.filter(
            status__in=['pending', 'pending_approval']
        ).select_for_update(skip_locked=True)[:5]
        
        for agent_run in pending_runs:
            # Check approval before claiming
            directive = agent_run.directive_snapshot or {}
            approval_required = directive.get('approval_required', False)
            
            if approval_required and agent_run.status == 'pending_approval':
                # Skip until approved
                continue
            
            # Claim with TTL
            agent_run.status = 'running'
            agent_run.save()
            
            try:
                logger.info(f"Executing agent run {agent_run.id}")
                executor.execute(agent_run)
                logger.info(f"Agent run {agent_run.id} completed with status {agent_run.status}")
            except Exception as e:
                logger.exception(f"Agent run {agent_run.id} failed: {e}")
                agent_run.status = 'failed'
                agent_run.error_message = str(e)
                agent_run.save()
