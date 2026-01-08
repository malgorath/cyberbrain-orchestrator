from django.shortcuts import render
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from .models import Directive, Run, Job, LLMCall, ContainerAllowlist
from .serializers import (
    DirectiveSerializer, RunSerializer, RunListSerializer, 
    JobSerializer, LLMCallSerializer, ContainerAllowlistSerializer,
    LaunchRunSerializer
)
import logging

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

        # Create the run
        run = Run.objects.create(
            directive=directive,
            status='pending'
        )

        # Create jobs for each task
        for task_type in tasks:
            Job.objects.create(
                run=run,
                task_type=task_type,
                status='pending'
            )

        logger.info(f"Launched run {run.id} with tasks: {tasks}")

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


def index(request):
    """Simple web UI homepage"""
    return render(request, 'orchestrator/index.html')

