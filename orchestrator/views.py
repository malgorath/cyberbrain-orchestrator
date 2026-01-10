from django.shortcuts import render
from django.utils import timezone
from django.http import FileResponse, Http404
from django.db.models import Sum, Count, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from .models import Directive, Run, Job, ContainerAllowlist
from .models import LLMCall as LegacyLLMCall
from core.models import RunArtifact
from core.models import LLMCall as CoreLLMCall
from .serializers import (
    DirectiveSerializer, RunSerializer, RunListSerializer, 
    JobSerializer, LLMCallSerializer, ContainerAllowlistSerializer,
    LaunchRunSerializer, RunArtifactSerializer, ScheduleSerializer
)
from core.models import Schedule as CoreSchedule, ScheduledRun as CoreScheduledRun, Job as CoreJob
from . import metrics
import logging
import os
from decimal import Decimal

logger = logging.getLogger(__name__)


class DirectiveViewSet(viewsets.ModelViewSet):
    """ViewSet for managing directives"""
    queryset = Directive.objects.all()
    serializer_class = DirectiveSerializer
    permission_classes = [AllowAny]


class RunViewSet(viewsets.ModelViewSet):
    """ViewSet for managing runs"""
    queryset = Run.objects.all()
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == 'list':
            return RunListSerializer
        return RunSerializer

    @action(detail=False, methods=['post'])
    def launch(self, request):
        """Launch a new orchestrator run with specified tasks"""
        serializer = LaunchRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tasks = serializer.validated_data.get('tasks', ['log_triage', 'gpu_report', 'service_map'])
        directive_id = serializer.validated_data.get('directive_id')
        target_host_id = serializer.validated_data.get('target_host_id')  # New: explicit host selection

        # Get or create default directive
        if directive_id:
            try:
                directive = Directive.objects.get(id=directive_id)
            except Directive.DoesNotExist:
                return Response(
                    {'error': 'Directive not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            directive, _ = Directive.objects.get_or_create(
                name='default',
                defaults={'description': 'Default orchestrator directive'}
            )

        # Select worker host (Phase 7)
        from orchestrator.host_router import HostRouter
        router = HostRouter()
        
        # Check if any task requires GPU
        requires_gpu = any(task in ['gpu_report', 'task2'] for task in tasks)
        
        try:
            selected_host = router.select_host(
                target_host_id=target_host_id,
                requires_gpu=requires_gpu
            )
        except Exception as e:
            return Response(
                {'error': f'Host selection failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the run
        run = Run.objects.create(
            directive=directive,
            status='pending',
            worker_host=selected_host  # New: assign worker host
        )
        
        # Increment active runs count
        router.increment_active_runs(selected_host)
        
        # Record metrics
        metrics.record_run_created(status='pending')

        # Create jobs for each task
        for task_type in tasks:
            Job.objects.create(
                run=run,
                task_type=task_type,
                status='pending'
            )
            metrics.record_job_created(task_key=task_type)

        # Create schedules for immediate execution (Phase 2 scheduler integration)
        from core.models import Job as CoreJob, Schedule, ScheduledRun
        from django.utils import timezone
        
        for task_type in tasks:
            # Get or create core.Job template for this task type
            core_job, _ = CoreJob.objects.get_or_create(
                task_key=task_type,
                defaults={
                    'name': f'{task_type.replace("_", " ").title()} Task',
                    'description': f'Auto-created job template for {task_type}',
                    'is_active': True
                }
            )
            
            # Create one-time schedule for immediate execution
            schedule = Schedule.objects.create(
                name=f'launch-run-{run.id}-{task_type}',
                job=core_job,
                directive=None,  # Will use directive from run
                custom_directive_text=f'Execute {task_type} for run {run.id}',
                enabled=True,
                schedule_type='interval',
                interval_minutes=999999,  # Effectively one-time (won't repeat)
                next_run_at=timezone.now(),  # Due immediately
                task3_scope='allowlist'
            )
            
            # Link schedule to existing run
            ScheduledRun.objects.create(
                schedule=schedule,
                run=run,
                status='pending',
                started_at=None
            )

        logger.info(f"Launched run {run.id} with tasks: {tasks} on host {selected_host.name}")

        return Response(
            RunSerializer(run).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['get'])
    def report(self, request, pk=None):
        """Fetch the report for a specific run in markdown and JSON format"""
        run = self.get_object()
        
        return Response({
            'id': run.id,
            'status': run.status,
            'markdown': run.report_markdown,
            'json': run.report_json,
            'started_at': run.started_at,
            'completed_at': run.completed_at,
        })
    
    @action(detail=True, methods=['get'])
    def artifacts(self, request, pk=None):
        """Get all artifacts for a specific run"""
        # Note: pk here is orchestrator.Run.id, not core.Run.id
        # Need to query by the orchestrator run's id
        artifacts = RunArtifact.objects.filter(run__id=pk)
        serializer = RunArtifactSerializer(artifacts, many=True)
        return Response(serializer.data)


class ScheduleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing schedules (core Schedule model)."""
    queryset = CoreSchedule.objects.all()
    serializer_class = ScheduleSerializer
    permission_classes = [AllowAny]

    @action(detail=True, methods=['post'], url_path='run-now')
    def run_now(self, request, pk=None):
        """Trigger an immediate run for the schedule, enforcing minimal constraints."""
        schedule = self.get_object()
        from orchestrator.models import Directive as LegacyDirective, Run as LegacyRun, Job as LegacyJob

        # Resolve directive: prefer core directive, else create legacy directive from custom text
        legacy_directive = None
        if schedule.directive:
            # Map core directive to legacy directive by name, create if missing
            legacy_directive, _ = LegacyDirective.objects.get_or_create(
                name=schedule.directive.name,
                defaults={
                    'description': schedule.directive.description or 'Imported from core directive',
                    'task_config': schedule.directive.task_config or {},
                }
            )
        elif schedule.custom_directive_text:
            # Create or reuse a directive derived from schedule name
            legacy_directive, _ = LegacyDirective.objects.get_or_create(
                name=f"schedule:{schedule.name}",
                defaults={
                    'description': schedule.custom_directive_text[:500],
                    'task_config': {},
                }
            )
        else:
            # Fallback to a default directive
            legacy_directive, _ = LegacyDirective.objects.get_or_create(
                name='default', defaults={'description': 'Default orchestrator directive'}
            )

        # Create legacy run and jobs (matching manual launch path)
        legacy_run = LegacyRun.objects.create(directive=legacy_directive, status='pending')

        # Jobs: single job based on schedule's job task_key
        task_type = schedule.job.task_key
        LegacyJob.objects.create(run=legacy_run, task_type=task_type, status='pending')

        # Link ScheduledRun entry
        sr = CoreScheduledRun.objects.create(schedule=schedule, run=legacy_run, status='started', started_at=timezone.now())

        # Update schedule timestamps deterministically
        schedule.last_run_at = timezone.now()
        schedule.compute_next_run()
        schedule.save()

        # Optionally execute run synchronously (best-effort)
        try:
            from orchestrator.services import OrchestratorService
            orchestrator = OrchestratorService()
            orchestrator.execute_run(legacy_run)
            sr.status = 'finished'
            sr.finished_at = timezone.now()
            sr.save()
        except Exception as e:
            logger.error(f"Run-now execution error: {e}")
            sr.status = 'failed'
            sr.error_summary = str(e)
            sr.finished_at = timezone.now()
            sr.save()

        return Response({'run_id': legacy_run.id}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def enable(self, request, pk=None):
        schedule = self.get_object()
        schedule.enabled = True
        if not schedule.next_run_at:
            schedule.compute_next_run()
        schedule.save()
        return Response({'id': schedule.id, 'enabled': schedule.enabled})

    @action(detail=True, methods=['post'])
    def disable(self, request, pk=None):
        schedule = self.get_object()
        schedule.enabled = False
        schedule.save()
        return Response({'id': schedule.id, 'enabled': schedule.enabled})

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        schedule = self.get_object()
        items = []
        for entry in schedule.history.all().order_by('-created_at')[:50]:
            items.append({
                'id': entry.id,
                'run_id': entry.run_id,
                'status': entry.status,
                'started_at': entry.started_at,
                'finished_at': entry.finished_at,
                'error_summary': entry.error_summary,
            })
        return Response({'items': items, 'count': len(items)})


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing jobs"""
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [AllowAny]


class ContainerAllowlistViewSet(viewsets.ModelViewSet):
    """ViewSet for managing container allowlist"""
    queryset = ContainerAllowlist.objects.all()
    serializer_class = ContainerAllowlistSerializer
    permission_classes = [AllowAny]


class RunArtifactViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for retrieving run artifacts"""
    queryset = RunArtifact.objects.all()
    serializer_class = RunArtifactSerializer
    permission_classes = [AllowAny]
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download artifact file content"""
        artifact = self.get_object()
        
        # Security: Ensure path is within /logs directory
        if not artifact.path.startswith('/logs/'):
            logger.warning(f"Attempted to access artifact outside /logs: {artifact.path}")
            raise Http404("Artifact not found")
        
        # Check if file exists
        if not os.path.exists(artifact.path):
            raise Http404("Artifact file not found on disk")
        
        # Serve file
        try:
            response = FileResponse(
                open(artifact.path, 'rb'),
                content_type='application/octet-stream'
            )
            filename = os.path.basename(artifact.path)
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        except Exception as e:
            logger.error(f"Error serving artifact file: {e}")
            raise Http404("Error reading artifact file")


def index(request):
    """Simple web UI homepage"""
    return render(request, 'orchestrator/index.html')


@api_view(['GET'])
@permission_classes([AllowAny])
def token_stats(request):
    """
    GET /api/token-stats/
    Returns aggregate token statistics across all LLM calls.
    SECURITY: Returns token counts only, never prompt/response content.
    """
    stats = CoreLLMCall.objects.aggregate(
        total_tokens=Sum('total_tokens'),
        total_prompt_tokens=Sum('prompt_tokens'),
        total_completion_tokens=Sum('completion_tokens'),
        call_count=Count('id')
    )
    
    # Handle None when no LLM calls exist
    return Response({
        'total_tokens': stats['total_tokens'] or 0,
        'total_prompt_tokens': stats['total_prompt_tokens'] or 0,
        'total_completion_tokens': stats['total_completion_tokens'] or 0,
        'call_count': stats['call_count'] or 0
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def cost_report(request):
    """
    GET /api/cost-report/
    Returns cost breakdown by model.
    Uses simple cost estimation: $0.002 per 1000 tokens (OpenAI gpt-3.5-turbo pricing)
    """
    # Cost per 1000 tokens by model (simplified)
    MODEL_COSTS = {
        'gpt-4': Decimal('0.03'),
        'gpt-3.5-turbo': Decimal('0.002'),
        'mistral-7b': Decimal('0.001'),
        'default': Decimal('0.002')
    }
    
    # Aggregate by model
    by_model = {}
    total_cost = Decimal('0')
    
    for call in CoreLLMCall.objects.all():
        model = call.model_id or 'unknown'
        tokens = call.total_tokens or 0
        cost_per_1k = MODEL_COSTS.get(model, MODEL_COSTS['default'])
        cost = (Decimal(tokens) / Decimal('1000')) * cost_per_1k
        
        if model not in by_model:
            by_model[model] = {
                'tokens': 0,
                'calls': 0,
                'estimated_cost': Decimal('0')
            }
        
        by_model[model]['tokens'] += tokens
        by_model[model]['calls'] += 1
        by_model[model]['estimated_cost'] += cost
        total_cost += cost
    
    # Convert Decimal to float for JSON serialization
    for model_data in by_model.values():
        model_data['estimated_cost'] = float(model_data['estimated_cost'])
    
    return Response({
        'total_cost': float(total_cost),
        'by_model': by_model,
        'note': 'Costs are estimates based on standard pricing'
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def usage_by_directive(request):
    """
    GET /api/usage-by-directive/
    Returns token usage aggregated by directive name (from run snapshots).
    Note: Uses directive_snapshot_name from core.Run model.
    """
    from core.models import Run as CoreRun
    
    # Get unique directive names from run snapshots
    directive_names = CoreRun.objects.values_list('directive_snapshot_name', flat=True).distinct()
    
    directives_usage = []
    for directive_name in directive_names:
        if not directive_name:
            continue
            
        runs = CoreRun.objects.filter(directive_snapshot_name=directive_name)
        
        stats = CoreLLMCall.objects.filter(run__in=runs).aggregate(
            total_tokens=Sum('total_tokens'),
            call_count=Count('id')
        )
        
        directives_usage.append({
            'directive_name': directive_name,
            'total_tokens': stats['total_tokens'] or 0,
            'call_count': stats['call_count'] or 0
        })
    
    return Response(directives_usage)


@api_view(['GET'])
@permission_classes([AllowAny])
def runs_since_last_success(request):
    """
    GET /api/runs/since-last-success/
    Returns all runs since the last successful run completion.
    Useful for "what changed since last success" queries.
    
    Response includes:
    - last_success_run: the most recent successful run (timestamp, status)
    - runs_since: list of all runs after that timestamp (pending, running, failed)
    - total_count: count of runs since last success
    """
    from core.models import Run as CoreRun
    from core.serializers import RunSerializer as CoreRunSerializer
    
    last_success = CoreRun.get_last_successful_run()
    
    if not last_success:
        return Response({
            'last_success_run': None,
            'runs_since': [],
            'total_count': 0,
            'note': 'No successful runs yet'
        })
    
    # Get all runs after the last successful run's end time
    # Include runs without ended_at (still pending/running)
    runs_since = CoreRun.objects.filter(
        Q(ended_at__gt=last_success.ended_at) | Q(ended_at__isnull=True)
    ).exclude(id=last_success.id).order_by('-started_at')
    
    return Response({
        'last_success_run': {
            'id': last_success.id,
            'status': last_success.status,
            'ended_at': last_success.ended_at,
        },
        'runs_since': CoreRunSerializer(runs_since, many=True).data,
        'total_count': runs_since.count(),
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def container_inventory(request):
    """
    GET /api/container-inventory/
    Returns current container allowlist and inventory snapshots.
    
    Provides:
    - allowlist: All whitelisted containers with enabled status
    - recent_snapshots: Recent container state snapshots
    """
    from core.models import ContainerAllowlist, ContainerInventory
    
    # Get active allowlist
    allowlist = ContainerAllowlist.objects.filter(enabled=True).values(
        'container_id', 'container_name', 'description', 'tags'
    ).order_by('container_name')
    
    # Get recent snapshots (last 10)
    recent_snapshots = ContainerInventory.objects.all().order_by('-created_at')[:10]
    
    snapshots_data = []
    for snapshot in recent_snapshots:
        snapshots_data.append({
            'id': snapshot.id,
            'container_id': snapshot.container_id,
            'container_name': snapshot.container_name,
            'created_at': snapshot.created_at,
            'run_id': snapshot.run_id if snapshot.run else None,
        })
    
    return Response({
        'allowlist': list(allowlist),
        'allowlist_count': allowlist.count(),
        'recent_snapshots': snapshots_data,
        'total_snapshots': ContainerInventory.objects.count(),
    })

class RepoCopilotViewSet(viewsets.ViewSet):
    """
    ViewSet for Repo Co-Pilot plans.
    
    Endpoints:
    - POST /api/repo-plans/launch/ - Launch a new repo plan
    - GET /api/repo-plans/ - List all plans
    - GET /api/repo-plans/{id}/ - Get plan details
    - POST /api/repo-plans/{id}/status/ - Get plan status
    - POST /api/repo-plans/{id}/report/ - Get plan report
    """
    permission_classes = [AllowAny]
    
    @action(detail=False, methods=['post'])
    def launch(self, request):
        """
        POST /api/repo-plans/launch/
        Launch a new repo copilot plan.
        
        Request:
        {
            "repo_url": "https://github.com/owner/repo",
            "base_branch": "main",
            "goal": "Add authentication",
            "directive_id": 1,
            "create_branch_flag": false,
            "push_flag": false
        }
        
        Response:
        {
            "repo_plan_id": 1,
            "status": "pending",
            "plan": {...},
            "created_at": "2024-01-01T00:00:00Z"
        }
        """
        from .serializers import LaunchRepoCopilotPlanSerializer
        from core.models import RepoCopilotPlan, Directive as CoreDirective
        from .services import RepoCopilotService
        
        serializer = LaunchRepoCopilotPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        repo_url = serializer.validated_data['repo_url']
        base_branch = serializer.validated_data['base_branch']
        goal = serializer.validated_data['goal']
        directive_id = serializer.validated_data['directive_id']
        create_branch_flag = serializer.validated_data.get('create_branch_flag', False)
        push_flag = serializer.validated_data.get('push_flag', False)
        
        # Get directive
        try:
            directive = CoreDirective.objects.get(id=directive_id)
        except CoreDirective.DoesNotExist:
            return Response(
                {'error': 'Directive not found'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate directive gating
        service = RepoCopilotService()
        flags = {'create_branch_flag': create_branch_flag, 'push_flag': push_flag}
        
        try:
            gating_result = service.validate_directive_gating(directive, flags)
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Create repo plan
        plan_obj = RepoCopilotPlan.objects.create(
            repo_url=repo_url,
            base_branch=base_branch,
            goal=goal,
            directive=directive,
            directive_snapshot=directive.to_json() if hasattr(directive, 'to_json') else {},
            status='pending',
        )
        
        # Generate plan
        try:
            plan_obj.status = 'generating'
            plan_obj.started_at = timezone.now()
            plan_obj.save()
            
            plan = service.generate_plan(repo_url, base_branch, goal, directive)
            
            plan_obj.plan = plan
            plan_obj.status = 'success'
            plan_obj.completed_at = timezone.now()
            plan_obj.save()
            
            return Response({
                'repo_plan_id': plan_obj.id,
                'status': plan_obj.status,
                'plan': plan,
                'created_at': plan_obj.created_at,
            }, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            plan_obj.status = 'failed'
            plan_obj.error_message = str(e)
            plan_obj.completed_at = timezone.now()
            plan_obj.save()
            logger.error(f"Failed to generate plan {plan_obj.id}: {e}")
            return Response(
                {'error': f'Failed to generate plan: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def list(self, request):
        """GET /api/repo-plans/ - List all repo plans"""
        from core.models import RepoCopilotPlan
        from .serializers import RepoCopilotPlanDetailSerializer
        
        plans = RepoCopilotPlan.objects.all().order_by('-created_at')
        data = []
        for plan in plans:
            data.append({
                'id': plan.id,
                'repo_url': plan.repo_url,
                'base_branch': plan.base_branch,
                'goal': plan.goal,
                'status': plan.status,
                'created_at': plan.created_at,
                'completed_at': plan.completed_at,
            })
        
        return Response({
            'count': len(data),
            'results': data,
        })
    
    def retrieve(self, request, pk=None):
        """GET /api/repo-plans/{id}/ - Get plan details"""
        from core.models import RepoCopilotPlan
        
        try:
            plan = RepoCopilotPlan.objects.get(id=pk)
        except RepoCopilotPlan.DoesNotExist:
            return Response(
                {'error': 'Plan not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            'id': plan.id,
            'repo_url': plan.repo_url,
            'base_branch': plan.base_branch,
            'goal': plan.goal,
            'status': plan.status,
            'plan': plan.plan,
            'created_at': plan.created_at,
            'started_at': plan.started_at,
            'completed_at': plan.completed_at,
            'error_message': plan.error_message,
        })
    
    @action(detail=True, methods=['post'])
    def status(self, request, pk=None):
        """POST /api/repo-plans/{id}/status/ - Get plan status"""
        from core.models import RepoCopilotPlan
        
        try:
            plan = RepoCopilotPlan.objects.get(id=pk)
        except RepoCopilotPlan.DoesNotExist:
            return Response(
                {'error': 'Plan not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            'id': plan.id,
            'status': plan.status,
            'created_at': plan.created_at,
            'completed_at': plan.completed_at,
            'duration_seconds': plan.duration_seconds(),
        })
    
    @action(detail=True, methods=['post'])
    def report(self, request, pk=None):
        """POST /api/repo-plans/{id}/report/ - Get plan report"""
        from core.models import RepoCopilotPlan
        
        try:
            plan = RepoCopilotPlan.objects.get(id=pk)
        except RepoCopilotPlan.DoesNotExist:
            return Response(
                {'error': 'Plan not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if plan.status == 'failed':
            return Response({
                'id': plan.id,
                'status': plan.status,
                'error_message': plan.error_message,
            })
        
        return Response({
            'id': plan.id,
            'status': plan.status,
            'summary': f"Plan for {plan.repo_url}@{plan.base_branch}",
            'markdown': plan.plan.get('markdown', ''),
            'plan_json': plan.plan,
            'created_at': plan.created_at,
            'completed_at': plan.completed_at,
        })


class WorkerHostViewSet(viewsets.ModelViewSet):
    """
    ViewSet for WorkerHost management.
    
    Endpoints:
    - GET /api/worker-hosts/ - List all hosts
    - POST /api/worker-hosts/ - Create new host
    - GET /api/worker-hosts/{id}/ - Get host details
    - PATCH /api/worker-hosts/{id}/ - Update host (e.g. toggle enabled)
    - DELETE /api/worker-hosts/{id}/ - Remove host
    - GET /api/worker-hosts/{id}/health/ - Get health status
    """
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        from core.models import WorkerHost
        return WorkerHost.objects.all()
    
    def get_serializer_class(self):
        from .serializers import WorkerHostSerializer
        return WorkerHostSerializer
    
    def list(self, request):
        """GET /api/worker-hosts/ - List all worker hosts."""
        hosts = self.get_queryset()
        
        data = []
        for host in hosts:
            data.append({
                'id': host.id,
                'name': host.name,
                'type': host.type,
                'base_url': host.base_url,
                'enabled': host.enabled,
                'healthy': host.healthy,
                'active_runs_count': host.active_runs_count,
                'capabilities': host.capabilities,
                'last_seen_at': host.last_seen_at,
                'created_at': host.created_at,
            })
        
        return Response({
            'count': len(data),
            'results': data,
        })
    
    def create(self, request):
        """POST /api/worker-hosts/ - Create new worker host."""
        from .serializers import WorkerHostSerializer
        from core.models import WorkerHost
        
        serializer = WorkerHostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        host = serializer.save()
        
        return Response({
            'id': host.id,
            'name': host.name,
            'type': host.type,
            'base_url': host.base_url,
            'enabled': host.enabled,
            'capabilities': host.capabilities,
        }, status=status.HTTP_201_CREATED)
    
    def retrieve(self, request, pk=None):
        """GET /api/worker-hosts/{id}/ - Get host details."""
        from core.models import WorkerHost
        
        try:
            host = WorkerHost.objects.get(id=pk)
        except WorkerHost.DoesNotExist:
            return Response(
                {'error': 'Host not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            'id': host.id,
            'name': host.name,
            'type': host.type,
            'base_url': host.base_url,
            'enabled': host.enabled,
            'healthy': host.healthy,
            'active_runs_count': host.active_runs_count,
            'capabilities': host.capabilities,
            'ssh_config': bool(host.ssh_config),  # Don't expose secrets
            'last_seen_at': host.last_seen_at,
            'created_at': host.created_at,
            'updated_at': host.updated_at,
        })
    
    def partial_update(self, request, pk=None):
        """PATCH /api/worker-hosts/{id}/ - Update host (e.g. toggle enabled)."""
        from core.models import WorkerHost
        
        try:
            host = WorkerHost.objects.get(id=pk)
        except WorkerHost.DoesNotExist:
            return Response(
                {'error': 'Host not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Allow updating: enabled, capabilities, name
        if 'enabled' in request.data:
            host.enabled = request.data['enabled']
        
        if 'capabilities' in request.data:
            host.capabilities = request.data['capabilities']
        
        if 'name' in request.data:
            host.name = request.data['name']
        
        host.save()
        
        return Response({
            'id': host.id,
            'name': host.name,
            'enabled': host.enabled,
            'capabilities': host.capabilities,
        })
    
    def destroy(self, request, pk=None):
        """DELETE /api/worker-hosts/{id}/ - Remove host."""
        from core.models import WorkerHost
        
        try:
            host = WorkerHost.objects.get(id=pk)
        except WorkerHost.DoesNotExist:
            return Response(
                {'error': 'Host not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if host has active runs
        if host.active_runs_count > 0:
            return Response(
                {'error': f'Cannot delete host with {host.active_runs_count} active runs'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        host.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['get'])
    def health(self, request, pk=None):
        """GET /api/worker-hosts/{id}/health/ - Get host health status."""
        from core.models import WorkerHost
        from orchestrator.health_checker import HealthChecker
        from django.utils import timezone
        
        try:
            host = WorkerHost.objects.get(id=pk)
        except WorkerHost.DoesNotExist:
            return Response(
                {'error': 'Host not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Optionally trigger health check
        if request.query_params.get('check', 'false').lower() == 'true':
            checker = HealthChecker()
            success = checker.check_host(host)
            host.refresh_from_db()
        else:
            # Always update last_seen_at on health endpoint access (heartbeat)
            host.last_seen_at = timezone.now()
            host.save(update_fields=['last_seen_at'])
        
        return Response({
            'host_id': host.id,
            'name': host.name,
            'healthy': host.healthy,
            'last_seen_at': host.last_seen_at,
            'is_stale': host.is_stale(),
            'active_runs_count': host.active_runs_count,
        })