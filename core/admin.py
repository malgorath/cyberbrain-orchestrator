from django.contrib import admin
from .models import (
    Directive, Job, Run, RunJob, LLMCall, RunArtifact,
    ContainerInventory, ContainerAllowlist, WorkerImageAllowlist,
    WorkerAudit, GPUState
)


@admin.register(Directive)
class DirectiveAdmin(admin.ModelAdmin):
    list_display = ['id', 'directive_type', 'name', 'version', 'is_active', 'created_at']
    list_filter = ['directive_type', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ['id', 'task_type', 'name', 'is_active', 'created_at']
    list_filter = ['task_type', 'is_active']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'started_at', 'completed_at', 'total_tokens']
    list_filter = ['status', 'started_at']
    readonly_fields = ['started_at', 'completed_at', 'total_prompt_tokens', 
                      'total_completion_tokens', 'total_tokens']
    search_fields = ['error_message']


@admin.register(RunJob)
class RunJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'run', 'job', 'status', 'started_at', 'completed_at', 'total_tokens']
    list_filter = ['status', 'job__task_type']
    readonly_fields = ['started_at', 'completed_at']
    search_fields = ['error_message']


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = ['id', 'run_job', 'model_id', 'endpoint', 'total_tokens', 
                   'success', 'created_at']
    list_filter = ['model_id', 'success', 'created_at']
    readonly_fields = ['created_at']
    search_fields = ['endpoint', 'model_id', 'error_type']


@admin.register(RunArtifact)
class RunArtifactAdmin(admin.ModelAdmin):
    list_display = ['id', 'run', 'artifact_type', 'file_path', 'file_size_bytes', 'created_at']
    list_filter = ['artifact_type', 'created_at']
    readonly_fields = ['created_at']
    search_fields = ['file_path', 'description']


@admin.register(ContainerInventory)
class ContainerInventoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'container_name', 'container_id', 'snapshot_at', 'run']
    list_filter = ['snapshot_at']
    readonly_fields = ['snapshot_at']
    search_fields = ['container_id', 'container_name']


@admin.register(ContainerAllowlist)
class ContainerAllowlistAdmin(admin.ModelAdmin):
    list_display = ['container_id', 'container_name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    readonly_fields = ['created_at', 'updated_at']
    search_fields = ['container_id', 'container_name', 'description']


@admin.register(WorkerImageAllowlist)
class WorkerImageAllowlistAdmin(admin.ModelAdmin):
    list_display = ['image_name', 'image_tag', 'requires_gpu', 'min_vram_mb', 
                   'is_active', 'created_at']
    list_filter = ['requires_gpu', 'is_active', 'created_at']
    readonly_fields = ['created_at', 'updated_at']
    search_fields = ['image_name', 'description']


@admin.register(WorkerAudit)
class WorkerAuditAdmin(admin.ModelAdmin):
    list_display = ['id', 'operation', 'container_id', 'image_name', 
                   'gpu_assigned', 'success', 'created_at']
    list_filter = ['operation', 'success', 'created_at']
    readonly_fields = ['created_at']
    search_fields = ['container_id', 'image_name', 'error_message']


@admin.register(GPUState)
class GPUStateAdmin(admin.ModelAdmin):
    list_display = ['gpu_id', 'gpu_name', 'free_vram_mb', 'total_vram_mb', 
                   'utilization_percent', 'active_workers', 'is_available', 'last_updated']
    list_filter = ['is_available', 'last_updated']
    readonly_fields = ['last_updated', 'created_at']
    search_fields = ['gpu_id', 'gpu_name']
