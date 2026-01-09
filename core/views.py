from rest_framework import viewsets

from .models import (
	Directive,
	Job,
	Run,
	RunArtifact,
	LLMCall,
	ContainerInventory,
	ContainerAllowlist,
)
from .serializers import (
	DirectiveSerializer,
	JobSerializer,
	RunSerializer,
	RunListSerializer,
	RunArtifactSerializer,
	LLMCallSerializer,
	ContainerInventorySerializer,
	ContainerAllowlistSerializer,
)


class DirectiveViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = Directive.objects.all().order_by('directive_type', 'name')
	serializer_class = DirectiveSerializer


class JobViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = Job.objects.select_related('default_directive').all().order_by('task_key', 'name')
	serializer_class = JobSerializer


class RunViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = Run.objects.select_related('job').prefetch_related('artifacts', 'llm_calls').order_by('-started_at')

	def get_serializer_class(self):
		if self.action == 'list':
			return RunListSerializer
		return RunSerializer


class RunArtifactViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = RunArtifact.objects.select_related('run').all().order_by('-created_at')
	serializer_class = RunArtifactSerializer


class LLMCallViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = LLMCall.objects.select_related('run').all().order_by('-created_at')
	serializer_class = LLMCallSerializer


class ContainerInventoryViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = ContainerInventory.objects.select_related('run').all().order_by('-created_at')
	serializer_class = ContainerInventorySerializer


class ContainerAllowlistViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = ContainerAllowlist.objects.all().order_by('container_name')
	serializer_class = ContainerAllowlistSerializer
