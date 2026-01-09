from rest_framework import serializers

from .models import (
    Directive,
    Job,
    Run,
    RunArtifact,
    LLMCall,
    ContainerInventory,
    ContainerAllowlist,
)


class DirectiveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Directive
        fields = [
            'id', 'directive_type', 'name', 'description', 'directive_text', 'is_builtin',
            'task_config', 'version', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class JobSerializer(serializers.ModelSerializer):
    default_directive = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Job
        fields = [
            'id', 'task_key', 'name', 'description', 'default_directive', 'config',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class RunArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = RunArtifact
        fields = ['id', 'artifact_type', 'path', 'file_size_bytes', 'mime_type', 'description', 'created_at']
        read_only_fields = ['id', 'created_at']


class LLMCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMCall
        fields = [
            'id', 'run', 'worker_id', 'endpoint', 'model_id',
            'prompt_tokens', 'completion_tokens', 'total_tokens', 'duration_ms', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ContainerInventorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ContainerInventory
        fields = ['id', 'container_id', 'container_name', 'snapshot_data', 'created_at', 'run']
        read_only_fields = ['id', 'created_at']


class ContainerAllowlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContainerAllowlist
        fields = ['container_id', 'container_name', 'description', 'enabled', 'tags', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class RunSerializer(serializers.ModelSerializer):
    job = JobSerializer(read_only=True)
    artifacts = RunArtifactSerializer(many=True, read_only=True)
    llm_calls = LLMCallSerializer(many=True, read_only=True)

    class Meta:
        model = Run
        fields = [
            'id', 'job', 'directive_snapshot_name', 'directive_snapshot_text',
            'status', 'started_at', 'ended_at',
            'report_markdown', 'report_json', 'report_markdown_path', 'report_json_path', 'output_path',
            'error_message', 'token_prompt', 'token_completion', 'token_total',
            'artifacts', 'llm_calls'
        ]
        read_only_fields = ['id', 'started_at', 'ended_at', 'token_prompt', 'token_completion', 'token_total']


class RunListSerializer(serializers.ModelSerializer):
    job = JobSerializer(read_only=True)

    class Meta:
        model = Run
        fields = ['id', 'job', 'status', 'started_at', 'ended_at', 'token_total']
        read_only_fields = ['id', 'started_at', 'ended_at', 'token_total']
