from rest_framework import serializers
from .models import Directive, Run, Job, LLMCall, ContainerAllowlist


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
    directive_id = serializers.IntegerField(required=False)
    tasks = serializers.ListField(
        child=serializers.ChoiceField(choices=['log_triage', 'gpu_report', 'service_map']),
        required=False,
        default=['log_triage', 'gpu_report', 'service_map']
    )


class ContainerAllowlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContainerAllowlist
        fields = ['id', 'container_id', 'name', 'description', 'created_at', 'is_active']
        read_only_fields = ['id', 'created_at']
