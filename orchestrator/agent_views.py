"""
Phase 5: Agent Run API endpoints

DRF ViewSet for agent run operations (launch, status, report, cancel).
Reuses existing Task 1/2/3 infrastructure.
"""

import json
import logging
from typing import Dict, Any

from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.serializers import Serializer, CharField, IntegerField, DictField, ValidationError

from core.models import AgentRun, AgentStep, Directive
from orchestrator.agent.planner import PlannerService
from orchestrator.agent.executor import AgentExecutor


logger = logging.getLogger(__name__)


class AgentLaunchSerializer(Serializer):
    """Serializer for agent run launch requests."""
    operator_goal = CharField(required=True, max_length=2000)
    directive_id = IntegerField(required=False, allow_null=True)
    custom_directive_text = CharField(required=False, allow_blank=True)
    max_steps = IntegerField(default=10, min_value=1, max_value=100)
    time_budget_minutes = IntegerField(default=60, min_value=1, max_value=1440)
    token_budget = IntegerField(default=10000, min_value=100, max_value=1000000)
    
    def validate(self, data):
        """Validate request data."""
        if not data.get('operator_goal', '').strip():
            raise ValidationError("operator_goal cannot be empty")
        
        directive_id = data.get('directive_id')
        if directive_id:
            try:
                Directive.objects.get(id=directive_id)
            except Directive.DoesNotExist:
                raise ValidationError(f"Directive {directive_id} not found")
        
        return data


class AgentRunViewSet(viewsets.ModelViewSet):
    """
    ViewSet for agent run operations.
    
    Endpoints:
    - GET /api/agent-runs/ - List all agent runs
    - GET /api/agent-runs/{id}/ - Get agent run details
    - POST /api/agent-runs/launch/ - Launch a new agent run
    - POST /api/agent-runs/{id}/status/ - Get current status
    - POST /api/agent-runs/{id}/report/ - Get final report
    - POST /api/agent-runs/{id}/cancel/ - Cancel execution
    """
    
    queryset = AgentRun.objects.all()
    permission_classes = [AllowAny]
    
    def get_serializer_class(self):
        if self.action == 'launch':
            return AgentLaunchSerializer
        return Serializer  # Default
    
    def list(self, request, *args, **kwargs):
        """List all agent runs."""
        runs = AgentRun.objects.all().order_by('-created_at')
        data = []
        for run in runs[:50]:  # Limit to last 50
            data.append({
                'id': run.id,
                'operator_goal': run.operator_goal[:100],
                'status': run.status,
                'current_step': run.current_step,
                'tokens_used': run.tokens_used,
                'token_budget': run.token_budget,
                'created_at': run.created_at.isoformat(),
                'started_at': run.started_at.isoformat() if run.started_at else None,
                'ended_at': run.ended_at.isoformat() if run.ended_at else None,
            })
        
        return Response({'results': data, 'count': len(data)})
    
    def retrieve(self, request, pk=None, *args, **kwargs):
        """Get agent run details."""
        try:
            agent_run = AgentRun.objects.get(id=pk)
        except AgentRun.DoesNotExist:
            return Response({'error': 'Agent run not found'}, status=status.HTTP_404_NOT_FOUND)
        
        steps = []
        for step in agent_run.steps.all().order_by('step_index'):
            steps.append({
                'step_index': step.step_index,
                'step_type': step.step_type,
                'task_id': step.task_id,
                'status': step.status,
                'task_run_id': step.task_run_id,
                'started_at': step.started_at.isoformat() if step.started_at else None,
                'ended_at': step.ended_at.isoformat() if step.ended_at else None,
                'duration_seconds': step.duration_seconds(),
                'error_message': step.error_message,
            })
        
        return Response({
            'id': agent_run.id,
            'operator_goal': agent_run.operator_goal,
            'status': agent_run.status,
            'current_step': agent_run.current_step,
            'max_steps': agent_run.max_steps,
            'time_budget_minutes': agent_run.time_budget_minutes,
            'token_budget': agent_run.token_budget,
            'tokens_used': agent_run.tokens_used,
            'started_at': agent_run.started_at.isoformat() if agent_run.started_at else None,
            'ended_at': agent_run.ended_at.isoformat() if agent_run.ended_at else None,
            'steps': steps,
            'error_message': agent_run.error_message,
        })
    
    @action(detail=False, methods=['post'])
    def launch(self, request):
        """
        Launch a new agent run.
        
        Request body:
        {
            "operator_goal": "Analyze system logs and report GPU usage",
            "directive_id": 1,  // Optional, defaults to first active
            "max_steps": 5,
            "time_budget_minutes": 10,
            "token_budget": 5000
        }
        
        Response:
        {
            "agent_run_id": 123,
            "status": "pending",
            "plan": [
                {"task_id": "log_triage", "step_index": 0, ...},
                {"task_id": "gpu_report", "step_index": 1, ...}
            ]
        }
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        goal = serializer.validated_data.get('operator_goal')
        directive_id = serializer.validated_data.get('directive_id')
        max_steps = serializer.validated_data.get('max_steps', 10)
        time_budget_minutes = serializer.validated_data.get('time_budget_minutes', 60)
        token_budget = serializer.validated_data.get('token_budget', 10000)
        
        # Get directive
        if directive_id:
            directive = Directive.objects.get(id=directive_id)
        else:
            directive = Directive.objects.filter(is_active=True).first()
            if not directive:
                return Response(
                    {'error': 'No active directive found'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Check approval requirement
        initial_status = 'pending_approval' if directive.approval_required else 'pending'
        
        # Generate plan
        try:
            planner = PlannerService()
            plan = planner.plan(goal, directive)
        except Exception as e:
            logger.error(f"Plan generation failed: {e}")
            return Response(
                {'error': f'Plan generation failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create agent run
        agent_run = AgentRun.objects.create(
            operator_goal=goal,
            directive_snapshot=directive.to_json(),
            status=initial_status,
            max_steps=max_steps,
            time_budget_minutes=time_budget_minutes,
            token_budget=token_budget,
        )
        
        # Create steps from plan
        for step_data in plan:
            AgentStep.objects.create(
                agent_run=agent_run,
                step_index=step_data.get('step_index', 0),
                step_type=step_data.get('step_type', 'task_call'),
                task_id=step_data.get('task_id', ''),
                inputs=step_data.get('inputs', {}),
                status='pending',
            )
        
        # If not approval-gated, execute immediately
        if initial_status != 'pending_approval':
            executor = AgentExecutor()
            try:
                executor.execute(agent_run)
            except Exception as e:
                logger.error(f"Agent execution failed: {e}")
                agent_run.status = 'failed'
                agent_run.error_message = str(e)
                agent_run.save()
        
        return Response({
            'agent_run_id': agent_run.id,
            'status': agent_run.status,
            'plan': plan,
            'created_at': agent_run.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def status(self, request, pk=None):
        """Get current status of an agent run."""
        try:
            agent_run = AgentRun.objects.get(id=pk)
        except AgentRun.DoesNotExist:
            return Response({'error': 'Agent run not found'}, status=status.HTTP_404_NOT_FOUND)
        
        return Response({
            'agent_run_id': agent_run.id,
            'status': agent_run.status,
            'current_step': agent_run.current_step,
            'max_steps': agent_run.max_steps,
            'tokens_used': agent_run.tokens_used,
            'token_budget': agent_run.token_budget,
            'time_elapsed_minutes': agent_run.time_elapsed_minutes(),
            'is_expired': agent_run.is_expired(),
        })
    
    @action(detail=True, methods=['post'])
    def report(self, request, pk=None):
        """Get final report for a completed agent run."""
        try:
            agent_run = AgentRun.objects.get(id=pk)
        except AgentRun.DoesNotExist:
            return Response({'error': 'Agent run not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Build report from steps
        steps_summary = []
        for step in agent_run.steps.all().order_by('step_index'):
            steps_summary.append({
                'step_index': step.step_index,
                'task_id': step.task_id,
                'status': step.status,
                'duration_seconds': step.duration_seconds(),
                'error': step.error_message if step.status == 'failed' else None,
            })
        
        report = {
            'agent_run_id': agent_run.id,
            'operator_goal': agent_run.operator_goal,
            'status': agent_run.status,
            'total_steps': len(steps_summary),
            'successful_steps': sum(1 for s in steps_summary if s['status'] == 'success'),
            'failed_steps': sum(1 for s in steps_summary if s['status'] == 'failed'),
            'tokens_used': agent_run.tokens_used,
            'token_budget': agent_run.token_budget,
            'time_elapsed_minutes': agent_run.time_elapsed_minutes(),
            'steps': steps_summary,
            'error_message': agent_run.error_message,
        }
        
        # Generate markdown report
        markdown = self._generate_markdown_report(agent_run, steps_summary)
        
        return Response({
            'summary': report,
            'markdown': markdown,
            'json': agent_run.report_json,
        })
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an agent run."""
        try:
            agent_run = AgentRun.objects.get(id=pk)
        except AgentRun.DoesNotExist:
            return Response({'error': 'Agent run not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if agent_run.status in ['completed', 'failed', 'cancelled']:
            return Response({
                'error': f'Cannot cancel agent run with status {agent_run.status}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        agent_run.status = 'cancelled'
        agent_run.ended_at = timezone.now()
        agent_run.save()
        
        return Response({
            'agent_run_id': agent_run.id,
            'status': 'cancelled',
        })
    
    def _generate_markdown_report(self, agent_run: AgentRun, steps_summary: list) -> str:
        """Generate markdown report from agent run."""
        lines = []
        lines.append(f"# Agent Run Report {agent_run.id}\n")
        lines.append(f"**Goal:** {agent_run.operator_goal}\n")
        lines.append(f"**Status:** {agent_run.status}\n")
        lines.append(f"**Duration:** {agent_run.time_elapsed_minutes():.1f} minutes\n")
        lines.append(f"**Tokens Used:** {agent_run.tokens_used} / {agent_run.token_budget}\n\n")
        
        lines.append("## Steps\n\n")
        for step_data in steps_summary:
            status_emoji = {
                'success': '✅',
                'failed': '❌',
                'pending': '⏳',
                'running': '▶️',
                'skipped': '⏭️',
            }.get(step_data['status'], '❓')
            
            lines.append(f"- {status_emoji} Step {step_data['step_index']}: "
                        f"{step_data['task_id']} ({step_data['duration_seconds']:.1f}s)\n")
            if step_data['error']:
                lines.append(f"  - Error: {step_data['error']}\n")
        
        if agent_run.error_message:
            lines.append(f"\n## Errors\n\n{agent_run.error_message}\n")
        
        return "".join(lines)
