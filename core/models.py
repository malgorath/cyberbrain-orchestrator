"""
Core models for Cyberbrain Orchestrator.

SECURITY GUARDRAILS:
- NEVER store LLM prompts or responses in the database
- Only store token counts (prompt_tokens, completion_tokens, total_tokens)
- When DEBUG_REDACTED_MODE is enabled, redact any content before logging
- All LLM interactions must go through token counting only
"""
from django.db import models
from django.utils import timezone
from django.db.models import Q


class Directive(models.Model):
    """
    Directive library (D1-D4) defining task templates and configurations.
    D1: Log Triage
    D2: GPU Report
    D3: Service Map
    D4: Custom directives
    """
    DIRECTIVE_TYPES = [
        ('D1', 'Log Triage (D1)'),
        ('D2', 'GPU Report (D2)'),
        ('D3', 'Service Map (D3)'),
        ('D4', 'Custom Directive (D4)'),
    ]
    
    directive_type = models.CharField(max_length=2, choices=DIRECTIVE_TYPES)
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    task_config = models.JSONField(default=dict, help_text="Configuration parameters for tasks")
    
    # Version control for directives
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['directive_type', 'name']
        indexes = [
            models.Index(fields=['directive_type', 'is_active']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.get_directive_type_display()}: {self.name}"


class Job(models.Model):
    """
    Job templates for Task 1-3.
    Task 1: Log Triage
    Task 2: GPU Report
    Task 3: Service Map
    """
    TASK_CHOICES = [
        ('task1', 'Task 1: Log Triage'),
        ('task2', 'Task 2: GPU Report'),
        ('task3', 'Task 3: Service Map'),
    ]
    
    task_type = models.CharField(max_length=10, choices=TASK_CHOICES)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    default_config = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['task_type', 'name']
        indexes = [
            models.Index(fields=['task_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.get_task_type_display()}: {self.name}"


class Run(models.Model):
    """
    Orchestrator run with status tracking (success/failure).
    Stores directive SNAPSHOT (not reference) to preserve exact configuration used.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),  # Changed from 'completed' for clarity
        ('failed', 'Failed'),
        ('partial', 'Partial Success'),  # Some jobs succeeded, some failed
    ]

    # Directive snapshot (stored at run creation time)
    # GUARDRAIL: This is a snapshot, not a reference, to preserve exact config
    directive_snapshot = models.JSONField(
        help_text="Complete directive configuration at time of run creation"
    )
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Report data - GUARDRAIL: Only markdown summary and structured JSON, NO raw LLM content
    report_markdown = models.TextField(
        blank=True,
        help_text="GUARDRAIL: Markdown summary only, NO LLM prompts/responses"
    )
    report_json = models.JSONField(
        default=dict,
        help_text="GUARDRAIL: Structured results only, NO LLM prompts/responses"
    )
    
    error_message = models.TextField(blank=True)
    
    # Total token usage across all jobs in this run
    total_prompt_tokens = models.IntegerField(default=0)
    total_completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['status', '-started_at']),
            models.Index(fields=['-completed_at']),
            # Index for "since last successful run" queries
            models.Index(fields=['status', '-completed_at'], name='idx_success_completed'),
        ]

    def __str__(self):
        return f"Run {self.id} - {self.status} ({self.started_at})"
    
    @classmethod
    def get_last_successful_run(cls):
        """Get the most recent successful run for 'since last success' queries."""
        return cls.objects.filter(status='success').order_by('-completed_at').first()


class RunJob(models.Model):
    """
    Individual job execution within a run.
    Links Run to Job template with execution details.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]
    
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name='run_jobs')
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='executions')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # GUARDRAIL: Result contains only structured data, NO LLM content
    result = models.JSONField(
        default=dict,
        help_text="GUARDRAIL: Structured results only, NO LLM prompts/responses"
    )
    error_message = models.TextField(blank=True)
    
    # Token usage for this specific job
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)

    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['run', 'status']),
            models.Index(fields=['job', '-started_at']),
        ]

    def __str__(self):
        return f"RunJob {self.id} - {self.job.name} ({self.status})"


class LLMCall(models.Model):
    """
    Tracks LLM API calls with token counts ONLY.
    
    CRITICAL GUARDRAIL:
    - NEVER store prompt content
    - NEVER store response content
    - ONLY store: endpoint, model_id, token counts, timestamps
    - In DEBUG_REDACTED_MODE, ensure no content leaks to logs
    """
    run_job = models.ForeignKey(RunJob, on_delete=models.CASCADE, related_name='llm_calls')
    
    # LLM endpoint and model information
    endpoint = models.CharField(
        max_length=255,
        help_text="LLM API endpoint (e.g., 'http://localhost:11434/api/generate')"
    )
    model_id = models.CharField(
        max_length=255,
        help_text="Model identifier (e.g., 'llama2', 'mistral')"
    )
    
    # Token counts ONLY - GUARDRAIL: NO content storage
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    
    # Metadata
    call_duration_ms = models.IntegerField(
        null=True,
        blank=True,
        help_text="Duration of API call in milliseconds"
    )
    success = models.BooleanField(default=True)
    error_type = models.CharField(max_length=100, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['run_job', '-created_at']),
            models.Index(fields=['model_id', '-created_at']),
            models.Index(fields=['endpoint', '-created_at']),
        ]

    def __str__(self):
        return f"LLMCall {self.id} - {self.model_id} ({self.total_tokens} tokens)"


class RunArtifact(models.Model):
    """
    File artifacts produced by runs, stored under /logs.
    Only stores paths and metadata, not content.
    """
    ARTIFACT_TYPES = [
        ('log', 'Log File'),
        ('report', 'Report File'),
        ('data', 'Data File'),
        ('other', 'Other'),
    ]
    
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name='artifacts')
    
    artifact_type = models.CharField(max_length=20, choices=ARTIFACT_TYPES)
    file_path = models.CharField(
        max_length=512,
        help_text="Relative path under CYBER_BRAIN_LOGS"
    )
    file_size_bytes = models.BigIntegerField(default=0)
    mime_type = models.CharField(max_length=100, blank=True)
    
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['run', 'artifact_type']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"Artifact {self.id} - {self.file_path}"


class ContainerInventory(models.Model):
    """
    Snapshots of container state at specific points in time.
    Used for tracking container changes and history.
    """
    container_id = models.CharField(max_length=255, db_index=True)
    container_name = models.CharField(max_length=255, db_index=True)
    
    # Snapshot data
    snapshot_data = models.JSONField(
        help_text="Complete container state snapshot (status, image, networks, etc.)"
    )
    
    # Snapshot metadata
    snapshot_at = models.DateTimeField(default=timezone.now)
    run = models.ForeignKey(
        Run,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='container_snapshots',
        help_text="Optional: Run that triggered this snapshot"
    )

    class Meta:
        ordering = ['-snapshot_at']
        indexes = [
            models.Index(fields=['container_id', '-snapshot_at']),
            models.Index(fields=['container_name', '-snapshot_at']),
            models.Index(fields=['-snapshot_at']),
        ]

    def __str__(self):
        return f"Inventory {self.id} - {self.container_name} @ {self.snapshot_at}"


class ContainerAllowlist(models.Model):
    """
    Whitelist of containers that can be accessed/monitored.
    container_id is the primary identifier.
    """
    container_id = models.CharField(
        max_length=255,
        primary_key=True,
        help_text="Docker container ID (full or short form)"
    )
    container_name = models.CharField(
        max_length=255,
        help_text="Container name metadata"
    )
    
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    # Additional metadata
    tags = models.JSONField(
        default=list,
        help_text="Tags for organizing containers"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['container_name']
        indexes = [
            models.Index(fields=['is_active', 'container_name']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.container_name} ({self.container_id[:12]})"


class WorkerImageAllowlist(models.Model):
    """
    Allowlist of Docker images that can be used for worker containers.
    Security control to prevent arbitrary image execution.
    """
    image_name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Docker image name (e.g., 'cyberbrain/worker:latest')"
    )
    image_tag = models.CharField(
        max_length=100,
        default='latest',
        help_text="Image tag/version"
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    # Resource requirements
    requires_gpu = models.BooleanField(default=False)
    min_vram_mb = models.IntegerField(
        default=0,
        help_text="Minimum VRAM required in MB (0 = no requirement)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['image_name']
        indexes = [
            models.Index(fields=['is_active', 'requires_gpu']),
        ]
        unique_together = [['image_name', 'image_tag']]

    def __str__(self):
        return f"{self.image_name}:{self.image_tag}"


class WorkerAudit(models.Model):
    """
    Audit log for worker container spawning and lifecycle.
    Records all worker operations for security and debugging.
    """
    OPERATION_TYPES = [
        ('spawn', 'Worker Spawned'),
        ('start', 'Worker Started'),
        ('stop', 'Worker Stopped'),
        ('remove', 'Worker Removed'),
        ('error', 'Worker Error'),
    ]
    
    run_job = models.ForeignKey(
        RunJob,
        on_delete=models.CASCADE,
        related_name='worker_audits',
        null=True,
        blank=True
    )
    
    operation = models.CharField(max_length=20, choices=OPERATION_TYPES)
    container_id = models.CharField(max_length=255, blank=True)
    image_name = models.CharField(max_length=255)
    
    # GPU allocation
    gpu_assigned = models.CharField(
        max_length=50,
        blank=True,
        help_text="GPU device ID assigned (e.g., '0', '1', 'none' for CPU)"
    )
    gpu_selection_reason = models.TextField(
        blank=True,
        help_text="Why this GPU was selected (VRAM headroom, utilization, etc.)"
    )
    
    # Worker configuration
    config_snapshot = models.JSONField(
        default=dict,
        help_text="Worker configuration at operation time"
    )
    
    # Result
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['run_job', '-created_at']),
            models.Index(fields=['operation', '-created_at']),
            models.Index(fields=['container_id']),
        ]

    def __str__(self):
        return f"WorkerAudit {self.id} - {self.operation} @ {self.created_at}"


class GPUState(models.Model):
    """
    Tracks GPU state for scheduling decisions.
    Updated periodically to maintain current GPU utilization and VRAM availability.
    """
    gpu_id = models.CharField(
        max_length=50,
        unique=True,
        help_text="GPU device identifier (e.g., '0', '1')"
    )
    gpu_name = models.CharField(
        max_length=255,
        help_text="GPU model name (e.g., 'NVIDIA GeForce RTX 4090')"
    )
    
    # Current state
    total_vram_mb = models.IntegerField(help_text="Total VRAM in MB")
    used_vram_mb = models.IntegerField(help_text="Currently used VRAM in MB")
    free_vram_mb = models.IntegerField(help_text="Available VRAM in MB")
    utilization_percent = models.FloatField(
        default=0.0,
        help_text="GPU utilization percentage (0-100)"
    )
    
    # Scheduling metadata
    is_available = models.BooleanField(default=True)
    active_workers = models.IntegerField(
        default=0,
        help_text="Number of workers currently using this GPU"
    )
    
    # Timestamps
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['gpu_id']
        indexes = [
            models.Index(fields=['is_available', 'utilization_percent']),
            models.Index(fields=['-last_updated']),
        ]

    def __str__(self):
        return f"GPU {self.gpu_id} - {self.gpu_name} ({self.utilization_percent}% util)"
    
    @property
    def scheduling_score(self):
        """
        Calculate scheduling score for GPU selection.
        Weighted blend of VRAM headroom and utilization.
        Lower score = better choice (most idle GPU first).
        """
        # Normalize VRAM headroom (0-1, higher is better)
        vram_headroom = self.free_vram_mb / self.total_vram_mb if self.total_vram_mb > 0 else 0
        
        # Normalize utilization (0-1, lower is better)
        util_normalized = self.utilization_percent / 100.0
        
        # Weighted blend: 60% VRAM headroom, 40% utilization
        # Invert vram_headroom because we want higher headroom = lower score
        score = (1 - vram_headroom) * 0.6 + util_normalized * 0.4
        
        return score
