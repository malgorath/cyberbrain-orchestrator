from django.contrib import admin
from .models import (
    Directive, Job, Run, RunJob, LLMCall, RunArtifact,
    ContainerInventory, ContainerAllowlist, WorkerImageAllowlist,
    WorkerAudit, GPUState
)


@admin.register(Directive)
class DirectiveAdmin(admin.ModelAdmin):
    list_display = ['id', 'directive_type', 'name', 'is_builtin', 'version', 'is_active', 'created_at']
    list_filter = ['directive_type', 'is_builtin', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ['id', 'task_key', 'default_directive', 'name', 'is_active', 'created_at']
    list_filter = ['task_key', 'default_directive', 'is_active']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ['id', 'job', 'status', 'started_at', 'ended_at', 'token_total']
    list_filter = ['status', 'started_at', 'ended_at']
    readonly_fields = ['started_at', 'ended_at', 'token_prompt',
                      'token_completion', 'token_total']
    search_fields = ['error_message', 'directive_snapshot_name']


@admin.register(RunJob)
class RunJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'run', 'job', 'status', 'started_at', 'completed_at', 'total_tokens']
    list_filter = ['status', 'job__task_key']
    readonly_fields = ['started_at', 'completed_at']
    search_fields = ['error_message']


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = ['id', 'run', 'worker_id', 'model_id', 'endpoint', 'total_tokens', 'created_at']
    list_filter = ['endpoint', 'model_id', 'created_at']
    readonly_fields = ['created_at']
    search_fields = ['endpoint', 'model_id', 'worker_id']


@admin.register(RunArtifact)
class RunArtifactAdmin(admin.ModelAdmin):
    list_display = ['id', 'run', 'artifact_type', 'path', 'file_size_bytes', 'created_at']
    list_filter = ['artifact_type', 'created_at']
    readonly_fields = ['created_at']
    search_fields = ['path', 'description']


@admin.register(ContainerInventory)
class ContainerInventoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'container_name', 'container_id', 'created_at', 'run']
    list_filter = ['created_at']
    readonly_fields = ['created_at']
    search_fields = ['container_id', 'container_name']


@admin.register(ContainerAllowlist)
class ContainerAllowlistAdmin(admin.ModelAdmin):
    list_display = ['container_id', 'container_name', 'enabled', 'created_at']
    list_filter = ['enabled', 'created_at']
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
