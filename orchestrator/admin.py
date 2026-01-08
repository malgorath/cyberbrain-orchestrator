from django.contrib import admin
from .models import Directive, Run, Job, LLMCall, ContainerAllowlist


@admin.register(Directive)
class DirectiveAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'created_at', 'updated_at']
    search_fields = ['name', 'description']
    list_filter = ['created_at']


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ['id', 'directive', 'status', 'started_at', 'completed_at']
    list_filter = ['status', 'started_at']
    search_fields = ['directive__name']
    readonly_fields = ['started_at', 'completed_at']


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ['id', 'run', 'task_type', 'status', 'started_at', 'completed_at']
    list_filter = ['task_type', 'status', 'started_at']
    readonly_fields = ['started_at', 'completed_at']


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = ['id', 'job', 'model_name', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'created_at']
    list_filter = ['model_name', 'created_at']
    readonly_fields = ['created_at']


@admin.register(ContainerAllowlist)
class ContainerAllowlistAdmin(admin.ModelAdmin):
    list_display = ['id', 'container_id', 'name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['container_id', 'name']
    readonly_fields = ['created_at']
