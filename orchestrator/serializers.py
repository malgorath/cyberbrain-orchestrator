from rest_framework import serializers
from django.utils import timezone
from .models import Directive, Run, Job, LLMCall, ContainerAllowlist
from core.models import RunArtifact
from core.models import Schedule as CoreSchedule, Job as CoreJob, Directive as CoreDirective


class DirectiveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Directive
        fields = ['id', 'name', 'description', 'task_config', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class LLMCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMCall
        fields = ['id', 'model_name', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'created_at']
        read_only_fields = ['id', 'created_at']


class JobSerializer(serializers.ModelSerializer):
    llm_calls = LLMCallSerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = ['id', 'task_type', 'status', 'started_at', 'completed_at', 'result', 'error_message', 'llm_calls']
        read_only_fields = ['id', 'started_at', 'completed_at']


class RunSerializer(serializers.ModelSerializer):
    jobs = JobSerializer(many=True, read_only=True)
    directive_name = serializers.CharField(source='directive.name', read_only=True)

    class Meta:
        model = Run
        fields = ['id', 'directive', 'directive_name', 'status', 'started_at', 'completed_at', 
                  'report_markdown', 'report_json', 'error_message', 'jobs']
        read_only_fields = ['id', 'started_at', 'completed_at']


class RunListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing runs"""
    directive_name = serializers.CharField(source='directive.name', read_only=True)
    job_count = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = ['id', 'directive', 'directive_name', 'status', 'started_at', 'completed_at', 'job_count']
        read_only_fields = ['id', 'started_at', 'completed_at']

    def get_job_count(self, obj):
        return obj.jobs.count()


class LaunchRunSerializer(serializers.Serializer):
    """Serializer for launching a new run"""
    directive = serializers.IntegerField(required=False)
    directive_id = serializers.IntegerField(required=False)
    tasks = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    task_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False
    )
    target_host_id = serializers.IntegerField(required=False, help_text='Explicit worker host ID (Phase 7)')

    def validate(self, attrs):
        directive_id = attrs.get('directive') or attrs.get('directive_id')
        tasks = attrs.get('tasks')
        task_ids = attrs.get('task_ids')

        if tasks and task_ids:
            raise serializers.ValidationError({'tasks': 'Use either tasks or task_ids, not both'})

        attrs['directive_id'] = directive_id
        return attrs


class TaskDefinitionSerializer(serializers.ModelSerializer):
    """Serializer for TaskDefinitions backed by core.Job."""
    key = serializers.CharField(source='task_key')
    enabled = serializers.BooleanField(source='is_active')
    default_config = serializers.JSONField(source='config')

    class Meta:
        model = CoreJob
        fields = [
            'id', 'key', 'name', 'description', 'enabled', 'default_config',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_key(self, value):
        qs = CoreJob.objects.filter(task_key=value)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError('Task key must be unique')
        return value


class ContainerAllowlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContainerAllowlist
        fields = ['id', 'container_id', 'name', 'description', 'created_at', 'is_active']
        read_only_fields = ['id', 'created_at']


class RunArtifactSerializer(serializers.ModelSerializer):
    """Serializer for run artifacts"""
    class Meta:
        model = RunArtifact
        fields = ['id', 'run', 'artifact_type', 'path', 'created_at']
        read_only_fields = ['id', 'created_at']


class ScheduleSerializer(serializers.ModelSerializer):
    """Serializer for core Schedule model with convenience fields."""
    task_key = serializers.CharField(write_only=True, required=False)
    task_id = serializers.IntegerField(write_only=True, required=False)
    directive_id = serializers.IntegerField(write_only=True, required=False)
    custom_directive_text = serializers.CharField(write_only=True, required=False, allow_blank=True)
    task_key_read = serializers.CharField(source='job.task_key', read_only=True)
    task_name = serializers.CharField(source='job.name', read_only=True)
    task_id_read = serializers.IntegerField(source='job.id', read_only=True)

    class Meta:
        model = CoreSchedule
        fields = [
            'id', 'name', 'enabled', 'schedule_type', 'interval_minutes', 'cron_expr', 'timezone',
            'task3_scope', 'max_global', 'max_per_job', 'last_run_at', 'next_run_at',
            # write-only inputs
            'task_key', 'task_id', 'directive_id', 'custom_directive_text',
            # read-only convenience
            'task_key_read', 'task_name', 'task_id_read',
        ]
        read_only_fields = ['id', 'last_run_at']

    def validate(self, attrs):
        schedule_type = attrs.get('schedule_type') or getattr(self.instance, 'schedule_type', None)
        interval_minutes = attrs.get('interval_minutes', getattr(self.instance, 'interval_minutes', None))
        cron_expr = attrs.get('cron_expr', getattr(self.instance, 'cron_expr', ''))
        next_run_at = attrs.get('next_run_at', getattr(self.instance, 'next_run_at', None))

        if schedule_type == 'interval' and not interval_minutes:
            raise serializers.ValidationError({'interval_minutes': 'Interval minutes required for interval schedules'})
        if schedule_type == 'cron' and not cron_expr:
            raise serializers.ValidationError({'cron_expr': 'Cron expression required for cron schedules'})
        if schedule_type == 'one_shot' and not next_run_at:
            raise serializers.ValidationError({'next_run_at': 'next_run_at required for one_shot schedules'})

        return attrs

    def create(self, validated_data):
        task_key = validated_data.pop('task_key', None)
        task_id = validated_data.pop('task_id', None)
        directive_id = validated_data.pop('directive_id', None)
        custom_text = validated_data.pop('custom_directive_text', '')

        if task_id:
            try:
                job = CoreJob.objects.get(id=task_id)
            except CoreJob.DoesNotExist:
                raise serializers.ValidationError({'task_id': 'Task not found'})
        elif task_key:
            try:
                job = CoreJob.objects.get(task_key=task_key)
            except CoreJob.DoesNotExist:
                raise serializers.ValidationError({'task_key': 'Unknown task key'})
        else:
            raise serializers.ValidationError({'task_key': 'Task key or task_id is required'})

        directive = None
        if directive_id:
            try:
                directive = CoreDirective.objects.get(id=directive_id)
            except CoreDirective.DoesNotExist:
                raise serializers.ValidationError({'directive_id': 'Directive not found'})

        schedule = CoreSchedule.objects.create(
            job=job,
            directive=directive,
            custom_directive_text=custom_text,
            **validated_data
        )
        # Compute initial next_run_at
        if schedule.schedule_type in ['interval', 'cron']:
            schedule.compute_next_run()
        elif schedule.schedule_type == 'one_shot' and not schedule.next_run_at:
            schedule.next_run_at = timezone.now()
        schedule.save()
        return schedule

    def update(self, instance, validated_data):
        # Allow updating standard fields; if schedule type changes, recompute next
        for field in ['name', 'enabled', 'schedule_type', 'interval_minutes', 'cron_expr', 'timezone',
                      'task3_scope', 'max_global', 'max_per_job', 'next_run_at']:
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        if 'task_id' in validated_data:
            task_id = validated_data['task_id']
            try:
                instance.job = CoreJob.objects.get(id=task_id)
            except CoreJob.DoesNotExist:
                raise serializers.ValidationError({'task_id': 'Task not found'})
        if 'task_key' in validated_data:
            task_key = validated_data['task_key']
            try:
                instance.job = CoreJob.objects.get(task_key=task_key)
            except CoreJob.DoesNotExist:
                raise serializers.ValidationError({'task_key': 'Unknown task key'})

        # Directive updates
        if 'directive_id' in validated_data:
            directive_id = validated_data['directive_id']
            if directive_id is None:
                instance.directive = None
            else:
                try:
                    instance.directive = CoreDirective.objects.get(id=directive_id)
                except CoreDirective.DoesNotExist:
                    raise serializers.ValidationError({'directive_id': 'Directive not found'})

        if 'custom_directive_text' in validated_data:
            instance.custom_directive_text = validated_data['custom_directive_text']

        # Recompute next run if schedule config changed
        if instance.schedule_type in ['interval', 'cron']:
            instance.compute_next_run()
        instance.save()
        return instance


class RepoCopilotPlanSerializer(serializers.Serializer):
    """Serializer for repo copilot plan"""
    files = serializers.ListField(child=serializers.DictField())
    edits = serializers.ListField(child=serializers.DictField())
    commands = serializers.ListField(child=serializers.DictField())
    checks = serializers.ListField(child=serializers.DictField())
    risk_notes = serializers.ListField(child=serializers.CharField())
    markdown = serializers.CharField()


class LaunchRepoCopilotPlanSerializer(serializers.Serializer):
    """Serializer for launching a repo copilot plan"""
    repo_url = serializers.URLField(required=True)
    base_branch = serializers.CharField(max_length=255, required=True)
    goal = serializers.CharField(required=True)
    directive_id = serializers.IntegerField(required=True)
    create_branch_flag = serializers.BooleanField(default=False)
    push_flag = serializers.BooleanField(default=False)
    
    def validate_directive_id(self, value):
        """Validate that directive exists"""
        try:
            CoreDirective.objects.get(id=value)
        except CoreDirective.DoesNotExist:
            raise serializers.ValidationError("Directive not found")
        return value
    
    def validate_repo_url(self, value):
        """Validate that repo URL is a valid GitHub URL"""
        if not ('github.com' in value or 'gitlab.com' in value or 'gitea' in value):
            raise serializers.ValidationError(
                "Repository URL must be from GitHub, GitLab, or Gitea"
            )
        return value


class RepoCopilotPlanDetailSerializer(serializers.Serializer):
    """Serializer for repo copilot plan details"""
    repo_plan_id = serializers.IntegerField()
    status = serializers.CharField()
    repo_url = serializers.CharField()
    base_branch = serializers.CharField()
    goal = serializers.CharField()
    plan = RepoCopilotPlanSerializer()
    created_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField(required=False, allow_null=True)
    error_message = serializers.CharField(required=False, allow_blank=True)

class WorkerHostSerializer(serializers.Serializer):
    """Serializer for WorkerHost."""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255)
    type = serializers.ChoiceField(choices=['docker_socket', 'docker_tcp'])
    base_url = serializers.CharField(max_length=500)
    capabilities = serializers.JSONField(default=dict)
    enabled = serializers.BooleanField(default=True)
    healthy = serializers.BooleanField(read_only=True)
    active_runs_count = serializers.IntegerField(read_only=True)
    last_seen_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    def create(self, validated_data):
        from core.models import WorkerHost
        return WorkerHost.objects.create(**validated_data)
    
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class WorkerHostHealthSerializer(serializers.Serializer):
    """Serializer for WorkerHost health status."""
    host_id = serializers.IntegerField()
    name = serializers.CharField()
    healthy = serializers.BooleanField()
    last_seen_at = serializers.DateTimeField(allow_null=True)
    is_stale = serializers.BooleanField()
    active_runs_count = serializers.IntegerField()
