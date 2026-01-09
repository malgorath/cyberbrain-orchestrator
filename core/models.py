"""
Core models for Cyberbrain Orchestrator.

SECURITY GUARDRAILS:
- NEVER store LLM prompts or responses in the database
- Only store token counts (prompt_tokens, completion_tokens, total_tokens)
- When DEBUG_REDACTED_MODE is enabled, redact any content before logging
- All LLM interactions must go through token counting only
"""
from django.db import models
from datetime import timedelta
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
    directive_text = models.TextField(blank=True, help_text="Directive text/body (optional)")
    is_builtin = models.BooleanField(default=False, help_text="True when this directive is part of the default D1-D4 library")
    
    # Phase 5: Agent planning constraints
    task_list = models.JSONField(
        default=list,
        help_text="List of allowed task IDs (log_triage, gpu_report, service_map)"
    )
    approval_required = models.BooleanField(default=False, help_text="Require human approval before execution")
    max_concurrent_runs = models.IntegerField(default=5, help_text="Max concurrent task runs")
    
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
    
    def to_json(self):
        """Serialize directive to JSON snapshot."""
        return {
            'id': self.id,
            'directive_type': self.directive_type,
            'name': self.name,
            'description': self.description,
            'task_config': self.task_config,
            'directive_text': self.directive_text,
            'task_list': self.task_list,
            'approval_required': self.approval_required,
            'max_concurrent_runs': self.max_concurrent_runs,
            'version': self.version,
            'created_at': self.created_at.isoformat(),
        }


class Job(models.Model):
    """Job templates for the three core tasks (log triage, GPU report, service map)."""
    TASK_CHOICES = [
        ('log_triage', 'Log Triage'),
        ('gpu_report', 'GPU Report'),
        ('service_map', 'Service Map'),
    ]

    task_key = models.CharField(max_length=50, choices=TASK_CHOICES)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    default_directive = models.ForeignKey(
        'Directive',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='default_for_jobs',
        help_text="Default directive applied to this task (D1/D2/D3)"
    )
    config = models.JSONField(default=dict, help_text="Default configuration for this task")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['task_key', 'name']
        indexes = [
            models.Index(fields=['task_key', 'is_active']),
            models.Index(fields=['default_directive', 'is_active']),
        ]

    def __str__(self):
        return f"{self.get_task_key_display()}: {self.name}"


class Run(models.Model):
    """
    Orchestrator run with status tracking (success/failure).
    Stores directive SNAPSHOT (not reference) to preserve exact configuration used.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    job = models.ForeignKey(
        Job,
        on_delete=models.PROTECT,
        related_name='runs',
        help_text="Job template for this run"
    )

    # Directive snapshot (stored at run creation time)
    directive_snapshot_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Directive name captured at run time (no content stored)"
    )
    directive_snapshot_text = models.TextField(
        blank=True,
        help_text="Directive text captured at run time (no prompts/responses)"
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Report data - GUARDRAIL: Only markdown summary and structured JSON, NO raw LLM content
    report_markdown = models.TextField(
        blank=True,
        help_text="GUARDRAIL: Markdown summary only, NO LLM prompts/responses"
    )
    report_json = models.JSONField(
        default=dict,
        help_text="GUARDRAIL: Structured results only, NO LLM prompts/responses"
    )
    # Paths/references for outputs under CYBER_BRAIN_LOGS
    report_markdown_path = models.CharField(
        max_length=512,
        blank=True,
        help_text="Relative path to markdown report under CYBER_BRAIN_LOGS"
    )
    report_json_path = models.CharField(
        max_length=512,
        blank=True,
        help_text="Relative path to JSON report under CYBER_BRAIN_LOGS"
    )
    output_path = models.CharField(
        max_length=512,
        blank=True,
        help_text="Base output path/reference for this run under CYBER_BRAIN_LOGS"
    )
    
    error_message = models.TextField(blank=True)
    
    # Token usage across the run - counts only
    token_prompt = models.IntegerField(default=0)
    token_completion = models.IntegerField(default=0)
    token_total = models.IntegerField(default=0)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['status', '-started_at']),
            models.Index(fields=['-ended_at']),
            # Index for "since last successful run" queries
            models.Index(fields=['status', '-ended_at'], name='idx_status_ended'),
            models.Index(fields=['job', 'status', 'ended_at'], name='idx_run_job_status_ended'),
        ]

    def __str__(self):
        return f"Run {self.id} - {self.status} ({self.started_at})"
    
    @classmethod
    def get_last_successful_run(cls):
        """Get the most recent successful run for 'since last success' queries."""
        return cls.objects.filter(status='success').order_by('-ended_at').first()


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
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name='llm_calls')
    worker_id = models.CharField(max_length=255, blank=True, help_text="Worker/container identifier")

    ENDPOINT_CHOICES = [
        ('vllm', 'vLLM'),
        ('llama_cpp', 'llama.cpp'),
    ]
    endpoint = models.CharField(
        max_length=50,
        choices=ENDPOINT_CHOICES,
        help_text="LLM endpoint type"
    )
    model_id = models.CharField(
        max_length=255,
        help_text="Model identifier (e.g., 'llama2', 'mistral')"
    )
    
    # Token counts ONLY - GUARDRAIL: NO content storage
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    
    duration_ms = models.IntegerField(
        null=True,
        blank=True,
        help_text="Duration of API call in milliseconds"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['run', '-created_at']),
            models.Index(fields=['model_id', '-created_at']),
            models.Index(fields=['endpoint', '-created_at']),
            models.Index(fields=['run', 'model_id']),
            models.Index(fields=['run', 'endpoint', '-created_at']),
            models.Index(fields=['run', 'endpoint', 'model_id', 'created_at'], name='idx_llmcall_tokens'),
        ]

    def __str__(self):
        return f"LLMCall {self.id} - {self.model_id} ({self.total_tokens} tokens)"


class RunArtifact(models.Model):
    """
    File artifacts produced by runs, stored under /logs.
    Only stores paths and metadata, not content.
    """
    ARTIFACT_TYPES = [
        ('markdown', 'Markdown Report'),
        ('json', 'JSON Report'),
        ('log', 'Log File'),
        ('data', 'Data File'),
        ('other', 'Other'),
    ]
    
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name='artifacts')
    
    artifact_type = models.CharField(max_length=20, choices=ARTIFACT_TYPES)
    path = models.CharField(
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
        return f"Artifact {self.id} - {self.path}"


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
    created_at = models.DateTimeField(default=timezone.now)
    run = models.ForeignKey(
        Run,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='container_snapshots',
        help_text="Optional: Run that triggered this snapshot"
    )
    
    # Phase 7: Multi-host tracking
    worker_host = models.ForeignKey(
        'WorkerHost',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='container_inventories',
        help_text="Host where this container was observed"
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['container_id', '-created_at']),
            models.Index(fields=['container_name', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"Inventory {self.id} - {self.container_name} @ {self.created_at}"


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
    enabled = models.BooleanField(default=True)
    
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
            models.Index(fields=['enabled', 'container_name']),
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


class Schedule(models.Model):
    """
    Phase 2: Schedules for automatic run triggering.

    Supports interval and cron scheduling with optional concurrency controls.
    """
    SCHEDULE_TYPES = [
        ('interval', 'Interval'),
        ('cron', 'Cron'),
    ]

    TASK_SCOPE_CHOICES = [
        ('allowlist', 'Allowlist Only'),
        ('all', 'All Containers'),
    ]

    name = models.CharField(max_length=255, unique=True)
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name='schedules')

    # Directive source: either reference to core.Directive or custom text
    directive = models.ForeignKey(
        Directive,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='schedules'
    )
    custom_directive_text = models.TextField(blank=True)

    enabled = models.BooleanField(default=True)
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_TYPES)
    interval_minutes = models.IntegerField(null=True, blank=True)
    cron_expr = models.CharField(max_length=100, blank=True)
    timezone = models.CharField(max_length=100, default='UTC')

    # Task 3 scope
    task3_scope = models.CharField(max_length=20, choices=TASK_SCOPE_CHOICES, default='allowlist')

    # Concurrency profile (optional)
    max_global = models.IntegerField(null=True, blank=True, help_text='Max concurrent runs across all jobs')
    max_per_job = models.IntegerField(null=True, blank=True, help_text='Max concurrent runs for this job type')

    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)

    # Claiming fields for concurrency-safe scheduling
    claimed_until = models.DateTimeField(null=True, blank=True)
    claimed_by = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['enabled', 'next_run_at']),
            models.Index(fields=['schedule_type']),
            models.Index(fields=['claimed_until']),
        ]

    def __str__(self):
        return f"Schedule {self.name} -> {self.job.task_key} ({self.schedule_type})"

    def compute_next_run(self, from_time=None):
        """Compute and set next_run_at deterministically based on schedule_type."""
        from datetime import datetime, timedelta
        try:
            from zoneinfo import ZoneInfo
        except Exception:
            ZoneInfo = None

        tz = None
        if ZoneInfo:
            try:
                tz = ZoneInfo(self.timezone)
            except Exception:
                tz = None

        now = from_time or timezone.now()
        if tz:
            # Ensure timezone aware
            if timezone.is_naive(now):
                now = now.replace(tzinfo=tz)
            else:
                now = now.astimezone(tz)

        if self.schedule_type == 'interval':
            minutes = self.interval_minutes or 0
            if minutes <= 0:
                return None
            next_time = now + timedelta(minutes=minutes)
            self.next_run_at = next_time
            return next_time

        if self.schedule_type == 'cron':
            # Use croniter to compute next occurrence
            try:
                from croniter import croniter
            except Exception:
                return None
            base = now
            itr = croniter(self.cron_expr, base)
            next_time = itr.get_next(datetime)
            # Attach timezone if set
            if tz and timezone.is_naive(next_time):
                next_time = next_time.replace(tzinfo=tz)
            self.next_run_at = next_time
            return next_time

        return None

    @classmethod
    def due(cls):
        """Return queryset of schedules due to run and not currently claimed.
        A schedule is considered due if:
        - enabled is True
        - next_run_at <= now
        - claimed_until is null or in the past (TTL expired)
        """
        now = timezone.now()
        return cls.objects.filter(
            enabled=True,
            next_run_at__lte=now
        ).filter(models.Q(claimed_until__isnull=True) | models.Q(claimed_until__lte=now))


class ScheduledRun(models.Model):
    """Link a schedule to an executed run and track status (no LLM content)."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('started', 'Started'),
        ('finished', 'Finished'),
        ('failed', 'Failed'),
    ]

    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name='history')
    # Link to legacy orchestrator Run for execution record
    run = models.ForeignKey('orchestrator.Run', on_delete=models.PROTECT, related_name='scheduled_entries')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['schedule', '-created_at']),
            models.Index(fields=['run']),
        ]

    def __str__(self):
        return f"ScheduledRun {self.id} - schedule={self.schedule_id} run={self.run_id} ({self.status})"


# ============================================================================
# Phase 3: RAG (Retrieval-Augmented Generation) Models
# ============================================================================
# SECURITY GUARDRAIL: RAG queries are HASHED, not stored as plaintext.
# Only embeddings and retrieved chunk references are persisted.


class UploadFile(models.Model):
    """
    Phase 3: Uploaded file for RAG ingestion.
    Status tracks ingestion pipeline progress.
    """
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    ]

    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64, unique=True, db_index=True)
    stored_path = models.CharField(max_length=512)  # /uploads/...
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    error_message = models.TextField(blank=True)
    
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['status', '-uploaded_at']),
            models.Index(fields=['sha256']),
        ]

    def __str__(self):
        return f"UploadFile {self.filename} ({self.status})"


class Document(models.Model):
    """
    Phase 3: Extracted document from an uploaded file.
    One upload may produce multiple documents (e.g., multi-page PDFs).
    """
    upload = models.ForeignKey(UploadFile, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=500)
    source = models.CharField(max_length=500, blank=True)  # Original filename or URL
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['upload', '-created_at']),
        ]

    def __str__(self):
        return f"Document {self.title}"


class Chunk(models.Model):
    """
    Phase 3: Text chunk from a document for embedding.
    Chunks are created during ingestion for vector search.
    """
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.IntegerField()
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['document', 'chunk_index']
        indexes = [
            models.Index(fields=['document', 'chunk_index']),
        ]
        unique_together = [['document', 'chunk_index']]

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document_id}"


class Embedding(models.Model):
    """
    Phase 3: Vector embedding for a chunk.
    Uses pgvector for efficient similarity search.
    
    SECURITY GUARDRAIL: Only stores vectors, not raw queries.
    """
    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name='embeddings')
    embedding_model_id = models.CharField(max_length=100)  # e.g., "sentence-transformers/all-MiniLM-L6-v2"
    # pgvector integration: migration 0007 converts JSONField to vector(384)
    # Django sees this as JSONField for now; actual storage is pgvector after migration
    vector = models.JSONField()  # Stores 384-dim float array; pgvector backend after migration 0007
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['chunk']),
            models.Index(fields=['embedding_model_id']),
        ]

    def __str__(self):
        return f"Embedding for {self.chunk_id} ({self.embedding_model_id})"


class RetrievalEvent(models.Model):
    """
    Phase 3: Log of RAG retrieval queries.
    
    CRITICAL SECURITY GUARDRAIL:
    - query_hash: SHA256 hash of the query text (for deduplication/analytics)
    - query_text: MUST NEVER BE STORED by default
    - Only metadata and statistics are persisted
    
    This model tracks retrieval events without storing sensitive query content.
    """
    run = models.ForeignKey(
        'orchestrator.Run',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='retrieval_events'
    )
    query_hash = models.CharField(max_length=64, db_index=True)  # SHA256 of query
    top_k = models.IntegerField()
    results_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # WARNING: Do NOT add query_text field. Query content must not be persisted.
    # Only hashes and metadata are stored for privacy and security.

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['run', '-created_at']),
            models.Index(fields=['query_hash']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"RetrievalEvent {self.id} (hash={self.query_hash[:8]}...)"


# ============================================================================
# Phase 4: Notifications, Auth, Approval, Network Policy
# ============================================================================


class NotificationTarget(models.Model):
    """
    Phase 4: Notification destinations for run status updates.
    
    Supports Discord webhooks and email notifications.
    """
    TYPE_CHOICES = [
        ('discord', 'Discord Webhook'),
        ('email', 'Email'),
    ]
    
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(help_text='Configuration: {"webhook_url": "..."} or {"email": "..."}')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['enabled', 'type']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.type})"


class RunNotification(models.Model):
    """
    Phase 4: Track notification delivery for run status changes.
    
    SECURITY GUARDRAIL: Payloads contain counts only, no LLM content.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    
    run = models.ForeignKey('orchestrator.Run', on_delete=models.CASCADE, related_name='notifications')
    target = models.ForeignKey(NotificationTarget, on_delete=models.CASCADE, related_name='notifications')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    sent_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['run', '-created_at']),
            models.Index(fields=['target', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"Notification for Run {self.run_id} to {self.target.name} ({self.status})"


class NetworkPolicyRecommendation(models.Model):
    """
    Phase 4: Network policy recommendations from Task 3 (service mapping).
    
    Stores proposed network policies as metadata for review.
    """
    run = models.ForeignKey('orchestrator.Run', on_delete=models.CASCADE, related_name='network_policies')
    source_service = models.CharField(max_length=255)
    target_service = models.CharField(max_length=255)
    port = models.IntegerField(null=True, blank=True)
    protocol = models.CharField(max_length=20, default='tcp')
    recommendation = models.TextField(help_text='Human-readable policy recommendation')
    policy_yaml = models.TextField(blank=True, help_text='Generated K8s NetworkPolicy YAML')
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['run', '-created_at']),
            models.Index(fields=['source_service', 'target_service']),
        ]
    
    def __str__(self):
        return f"Policy: {self.source_service} → {self.target_service} (Run {self.run_id})"


# ============================================================================
# Phase 5: Agent Runs (Autonomy MVP) - Multi-step Workflows
# ============================================================================
# SECURITY GUARDRAIL: Agent runs do NOT store LLM prompts/responses.
# Token counts only; outputs are references to files (not inline).


class AgentRun(models.Model):
    """
    Phase 5: Autonomous multi-step workflow execution.
    
    An AgentRun chains multiple task executions (Task 1/2/3) based on a plan
    generated from an operator's goal and a directive. Tracks budgets and execution state.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('pending_approval', 'Pending Approval'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('timeout', 'Timeout'),
        ('expired', 'Expired (Budget)'),
    ]
    
    # Operator input
    operator_goal = models.TextField(help_text="Human-written goal/prompt for the agent")
    
    # Directive snapshot (for reproducibility)
    directive_snapshot = models.JSONField(
        default=dict,
        help_text="Directive configuration at agent creation time (no prompts/responses)"
    )
    
    # Execution state
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    current_step = models.IntegerField(default=0, help_text="Index of currently executing step")
    
    # Budgets
    max_steps = models.IntegerField(default=10)
    time_budget_minutes = models.IntegerField(default=60)
    token_budget = models.IntegerField(default=10000)
    
    # Token tracking (counts only, per security guardrail)
    tokens_used = models.IntegerField(default=0)
    
    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Report output (paths and metadata, no LLM content)
    report_markdown = models.TextField(blank=True, help_text="Final markdown report")
    report_json = models.JSONField(
        default=dict,
        help_text="Structured results (no prompts/responses)"
    )
    
    error_message = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['-ended_at']),
            models.Index(fields=['status', 'current_step']),
        ]
    
    def __str__(self):
        return f"AgentRun {self.id} - {self.operator_goal[:50]}... ({self.status})"
    
    def time_elapsed_minutes(self):
        """Get elapsed time in minutes since agent start."""
        if not self.started_at:
            return 0
        end = self.ended_at or timezone.now()
        delta = end - self.started_at
        return delta.total_seconds() / 60.0
    
    def is_expired(self):
        """Check if time budget has been exceeded."""
        return self.time_elapsed_minutes() > self.time_budget_minutes
    
    def tokens_remaining(self):
        """Get remaining token budget."""
        return max(0, self.token_budget - self.tokens_used)


class AgentStep(models.Model):
    """
    Phase 5: Single step within an agent run.
    
    Can be: task_call (execute Task 1/2/3), decision (branch logic),
    wait (delay), notify (send notification).
    
    SECURITY GUARDRAIL: inputs stored as config; outputs_ref is path-only.
    """
    STEP_TYPES = [
        ('task_call', 'Task Call'),
        ('decision', 'Decision'),
        ('wait', 'Wait'),
        ('notify', 'Notify'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]
    
    agent_run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name='steps')
    step_index = models.IntegerField()
    
    # Step definition
    step_type = models.CharField(max_length=20, choices=STEP_TYPES)
    task_id = models.CharField(max_length=100, blank=True, help_text="Task ID for task_call steps (log_triage, gpu_report, service_map)")
    
    # Inputs (configuration only, no prompts)
    inputs = models.JSONField(
        default=dict,
        help_text="Step inputs/parameters (no LLM content)"
    )
    
    # Outputs reference (paths only, not inline content)
    outputs_ref = models.CharField(
        max_length=512,
        blank=True,
        help_text="Path/reference to step outputs under CYBER_BRAIN_LOGS"
    )
    
    # Execution state
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)
    
    # Related run (if task_call)
    task_run_id = models.IntegerField(null=True, blank=True, help_text="ID of launched Run for task_call steps")
    
    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['agent_run', 'step_index']
        indexes = [
            models.Index(fields=['agent_run', 'step_index']),
            models.Index(fields=['agent_run', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]
        unique_together = [['agent_run', 'step_index']]
    
    def __str__(self):
        return f"Step {self.step_index}/{self.agent_run_id} - {self.step_type} ({self.status})"
    
    def duration_seconds(self):
        """Get step execution duration in seconds."""
        if not self.started_at:
            return 0
        end = self.ended_at or timezone.now()
        delta = end - self.started_at
        return delta.total_seconds()


class RepoCopilotPlan(models.Model):
    """
    Phase 6: Repository Co-Pilot Plans
    
    Stores PR plans generated for GitHub repositories.
    No auto-merge; plan generation only by default.
    
    SECURITY GUARDRAILS:
    - GitHub tokens stored server-side only, never in artifacts
    - Token counts only; no prompt/response storage
    - Directive gating: D1/D2 plan-only, D3+ branch creation, D4+ push/PR
    - No secrets in markdown/JSON output
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('generating', 'Generating Plan'),
        ('success', 'Plan Generated'),
        ('failed', 'Failed'),
    ]
    
    # Plan metadata
    repo_url = models.URLField(max_length=500)
    base_branch = models.CharField(max_length=255)
    goal = models.TextField()
    
    # Directive snapshot (from core Directive)
    directive = models.ForeignKey(
        Directive,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='repo_copilot_plans'
    )
    directive_snapshot = models.JSONField(
        default=dict,
        help_text="Snapshot of directive at plan generation time"
    )
    
    # Plan output
    plan = models.JSONField(
        default=dict,
        help_text="Plan structure: files, edits, commands, checks, risk_notes, markdown"
    )
    
    # Status and timestamps
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    
    # Token tracking (SECURITY GUARDRAIL: counts only, no prompts)
    tokens_used = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['repo_url', '-created_at']),
        ]
    
    def __str__(self):
        return f"RepoCopilotPlan {self.id} - {self.repo_url}@{self.base_branch} ({self.status})"
    
    def duration_seconds(self):
        """Get plan generation duration in seconds."""
        if not self.started_at:
            return 0
        end = self.completed_at or timezone.now()
        delta = end - self.started_at
        return delta.total_seconds()


class WorkerHost(models.Model):
    """
    Phase 7: Multi-Host Worker Management
    
    Represents a Docker host capable of executing orchestrator tasks.
    Supports both local (docker_socket) and remote (docker_tcp) hosts.
    
    LAN-ONLY constraint: Only private network IPs allowed.
    SSH tunnel support for secure remote Docker access.
    """
    
    TYPE_CHOICES = [
        ('docker_socket', 'Docker Socket (Local)'),
        ('docker_tcp', 'Docker TCP (Remote)'),
    ]
    
    # Host identification
    name = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    base_url = models.CharField(
        max_length=500,
        help_text="Docker connection URL (unix:///path or tcp://host:port)"
    )
    
    # Capabilities
    capabilities = models.JSONField(
        default=dict,
        help_text="Host capabilities: gpus, gpu_count, labels, max_concurrency"
    )
    
    # SSH tunnel configuration (for docker_tcp with SSH)
    ssh_config = models.JSONField(
        default=dict,
        help_text="SSH connection info: host, port, user, key_path (secrets, not logged)"
    )
    
    # State management
    enabled = models.BooleanField(default=True, help_text="Host available for task execution")
    healthy = models.BooleanField(default=True, help_text="Health check status")
    active_runs_count = models.IntegerField(default=0, help_text="Number of active runs on this host")
    
    # Health tracking
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text="Last successful health check")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['enabled', 'healthy']),
            models.Index(fields=['-last_seen_at']),
            models.Index(fields=['type']),
        ]
    
    def __str__(self):
        # Don't expose SSH credentials in string representation
        status = "enabled" if self.enabled else "disabled"
        health = "healthy" if self.healthy else "unhealthy"
        return f"{self.name} ({self.type}, {status}, {health})"
    
    def is_stale(self, threshold_minutes=5):
        """Check if host hasn't been seen recently."""
        if not self.last_seen_at:
            return True
        
        threshold = timezone.now() - timedelta(minutes=threshold_minutes)
        return self.last_seen_at < threshold
    
    def is_available(self):
        """Check if host is available for task execution."""
        return self.enabled and self.healthy
    
    def has_capacity(self):
        """Check if host has available capacity."""
        max_concurrency = self.capabilities.get('max_concurrency', 5)
        return self.active_runs_count < max_concurrency
    
    def has_gpu(self):
        """Check if host has GPU capability."""
        return self.capabilities.get('gpus', False)
