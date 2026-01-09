"""
Phase 5: Agent Executor

Executes agent run plans step-by-step with budget enforcement and error handling.
Launches existing Task runs (1/2/3) as sub-steps.
"""

import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from django.utils import timezone
from django.db import transaction

from core.models import AgentRun, AgentStep, Directive
from orchestrator.models import Run, Job, LLMCall


logger = logging.getLogger(__name__)


class RunLauncher:
    """
    Helper to launch existing Task runs (Task 1/2/3).
    Reuses current launch infrastructure.
    """
    
    def launch(self, task_id: str, directive, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Launch a task run.
        
        Args:
            task_id: log_triage, gpu_report, or service_map
            directive: Directive instance
            inputs: Step inputs/parameters
        
        Returns:
            Dict with run_id, status, etc.
        """
        from orchestrator.models import Job as OrchestratorJob
        
        # Map task_id to task_key
        task_mapping = {
            'log_triage': 'log_triage',
            'gpu_report': 'gpu_report',
            'service_map': 'service_map',
        }
        
        task_key = task_mapping.get(task_id)
        if not task_key:
            raise ValueError(f"Unknown task_id: {task_id}")
        
        # Find or create Job in orchestrator app
        job, created = OrchestratorJob.objects.get_or_create(
            task_key=task_key,
            defaults={
                'name': f'{task_key} Job',
                'description': f'Launched by agent executor',
            }
        )
        
        # Create Run in orchestrator app
        run = Run.objects.create(
            job=job,
            status='pending',
            directive_snapshot_name=directive.name,
        )
        
        return {
            'run_id': run.id,
            'status': 'pending',
            'launched_at': run.started_at.isoformat(),
        }


class AgentExecutor:
    """
    Executes agent run plans step-by-step.
    
    Features:
    - Budget enforcement (max_steps, time, tokens)
    - Stop conditions (approval gate, budget exceeded)
    - Automatic retry for transient failures
    - Token tracking
    """
    
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    
    def __init__(self):
        self.launcher = RunLauncher()
    
    def execute(self, agent_run: AgentRun) -> None:
        """
        Execute an agent run step-by-step.
        
        Updates agent_run.status, current_step, tokens_used, etc.
        
        Stop conditions:
        - Approval gate blocks if directive requires it
        - max_steps exceeded
        - time_budget exceeded
        - token_budget exceeded
        - Agent cancelled
        
        Args:
            agent_run: AgentRun instance to execute
        """
        # Check approval gate first
        if agent_run.status == 'pending_approval':
            logger.info(f"Agent {agent_run.id} waiting for approval")
            return
        
        # Mark as started
        if not agent_run.started_at:
            agent_run.started_at = timezone.now()
        
        agent_run.status = 'running'
        agent_run.save()
        
        directive = self._load_directive(agent_run)
        steps = agent_run.steps.all().order_by('step_index')
        
        try:
            for step in steps:
                # Budget checks before each step
                if self._check_max_steps_exceeded(agent_run, step.step_index):
                    logger.info(f"Agent {agent_run.id} reached max_steps at step {step.step_index}")
                    agent_run.status = 'completed'
                    break
                
                if self._check_time_budget(agent_run):
                    logger.info(f"Agent {agent_run.id} exceeded time budget")
                    agent_run.status = 'timeout'
                    break
                
                if self._check_token_budget(agent_run):
                    logger.info(f"Agent {agent_run.id} exceeded token budget")
                    agent_run.status = 'expired'
                    break
                
                # Execute step
                self._execute_step(agent_run, step, directive)
                
                agent_run.current_step = step.step_index + 1
                agent_run.save()
                
                # Stop if step failed
                if step.status == 'failed':
                    agent_run.status = 'failed'
                    agent_run.error_message = f"Step {step.step_index} failed: {step.error_message}"
                    break
                
                # Small delay between steps
                time.sleep(0.5)
        
        except Exception as e:
            logger.exception(f"Agent {agent_run.id} execution error: {e}")
            agent_run.status = 'failed'
            agent_run.error_message = str(e)
        
        finally:
            # Finalize
            if agent_run.status in ['running']:
                agent_run.status = 'completed'
            agent_run.ended_at = timezone.now()
            agent_run.save()
    
    def _execute_step(self, agent_run: AgentRun, step: AgentStep, directive: Directive) -> None:
        """Execute a single step (with retry logic)."""
        step.status = 'running'
        step.started_at = timezone.now()
        step.save()
        
        retry_count = 0
        
        while retry_count < self.MAX_RETRIES:
            try:
                if step.step_type == 'task_call':
                    self._execute_task_call(agent_run, step, directive)
                elif step.step_type == 'wait':
                    self._execute_wait(step)
                elif step.step_type == 'decision':
                    self._execute_decision(step)
                elif step.step_type == 'notify':
                    self._execute_notify(step)
                
                # Success
                step.status = 'success'
                step.ended_at = timezone.now()
                step.save()
                return
            
            except Exception as e:
                retry_count += 1
                if retry_count >= self.MAX_RETRIES:
                    logger.error(f"Step {step.id} failed after {self.MAX_RETRIES} retries: {e}")
                    step.status = 'failed'
                    step.error_message = str(e)
                    step.ended_at = timezone.now()
                    step.save()
                    return
                
                logger.warning(f"Step {step.id} failed, retrying ({retry_count}/{self.MAX_RETRIES}): {e}")
                time.sleep(self.RETRY_DELAY_SECONDS)
    
    def _execute_task_call(self, agent_run: AgentRun, step: AgentStep, directive: Directive) -> None:
        """Execute a task_call step (launch Task 1/2/3)."""
        task_id = step.task_id
        if not task_id:
            raise ValueError(f"Step {step.id} missing task_id")
        
        # Launch task run
        result = self.launcher.launch(task_id, directive, step.inputs)
        run_id = result['run_id']
        
        step.task_run_id = run_id
        step.outputs_ref = f"runs/{run_id}/report"
        
        # Update tokens from task run's LLM calls (if any)
        task_run = Run.objects.get(id=run_id)
        llm_calls = task_run.llm_calls.all()
        step_tokens = sum(call.total_tokens for call in llm_calls)
        
        agent_run.tokens_used += step_tokens
        agent_run.save()
    
    def _execute_wait(self, step: AgentStep) -> None:
        """Execute a wait step (delay)."""
        seconds = step.inputs.get('seconds', 1)
        time.sleep(seconds)
    
    def _execute_decision(self, step: AgentStep) -> None:
        """Execute a decision step (placeholder)."""
        # Stub: decisions would involve conditional logic based on prev step outputs
        pass
    
    def _execute_notify(self, step: AgentStep) -> None:
        """Execute a notify step (placeholder)."""
        # Stub: notifications would send status updates
        pass
    
    def _load_directive(self, agent_run: AgentRun) -> Optional[Directive]:
        """Reconstruct directive from agent_run snapshot."""
        if not agent_run.directive_snapshot:
            return None
        
        # Try to find directive by snapshot name
        snapshot = agent_run.directive_snapshot
        if isinstance(snapshot, dict):
            directive_id = snapshot.get('id')
            if directive_id:
                return Directive.objects.filter(id=directive_id).first()
        
        # Fallback: use first active directive
        return Directive.objects.filter(is_active=True).first()
    
    def _check_max_steps_exceeded(self, agent_run: AgentRun, step_index: int) -> bool:
        """Check if max_steps budget is exceeded."""
        return step_index >= agent_run.max_steps
    
    def _check_time_budget(self, agent_run: AgentRun) -> bool:
        """Check if time_budget_minutes is exceeded."""
        if not agent_run.started_at:
            return False
        
        elapsed_minutes = (timezone.now() - agent_run.started_at).total_seconds() / 60.0
        return elapsed_minutes > agent_run.time_budget_minutes
    
    def _check_token_budget(self, agent_run: AgentRun) -> bool:
        """Check if token_budget is exceeded."""
        return agent_run.tokens_used >= agent_run.token_budget
