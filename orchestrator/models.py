from django.db import models
from django.utils import timezone


class Directive(models.Model):
    """Defines a directive/template for orchestrator tasks"""
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    task_config = models.JSONField(default=dict)  # Task configuration
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Run(models.Model):
    """Represents an orchestrator run"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    directive = models.ForeignKey(Directive, on_delete=models.CASCADE, related_name='runs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    report_markdown = models.TextField(blank=True)
    report_json = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)
    
    # Phase 3: RAG integration toggle
    use_rag = models.BooleanField(
        default=False,
        help_text='If True, perform RAG retrieval before LLM calls in this run'
    )
    
    # Phase 4: Approval gating for D3/D4 directives
    APPROVAL_CHOICES = [
        ('none', 'No Approval Required'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
    ]
    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='none')
    approved_by = models.CharField(max_length=255, blank=True, help_text='Username or identifier of approver')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Phase 7: Multi-host worker assignment
    worker_host = models.ForeignKey(
        'core.WorkerHost',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='runs',
        help_text='Worker host assigned to execute this run'
    )

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Run {self.id} - {self.directive.name} ({self.status})"


class Job(models.Model):
    """Represents a job within a run"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    TASK_CHOICES = [
        ('log_triage', 'Log Triage'),
        ('gpu_report', 'GPU Report'),
        ('service_map', 'Service Map'),
        ('repo_copilot_plan', 'Repo Co-Pilot Plan'),  # Phase 6: Repo Co-Pilot
    ]

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name='jobs')
    task_type = models.CharField(max_length=50, choices=TASK_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"Job {self.id} - {self.task_type} ({self.status})"


class LLMCall(models.Model):
    """Tracks LLM API calls with token counts"""
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='llm_calls')
    model_name = models.CharField(max_length=255)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"LLMCall {self.id} - {self.model_name} ({self.total_tokens} tokens)"


class ContainerAllowlist(models.Model):
    """Allowlist of containers that can be accessed"""
    container_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.container_id})"
