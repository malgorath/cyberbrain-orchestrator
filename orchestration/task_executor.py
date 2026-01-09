"""
E7 Task Executor Service

Orchestrates execution of all 3 task workers:
- Task 1: log_triage (log collection + LLM analysis)
- Task 2: gpu_report (GPU metrics analysis)
- Task 3: service_map (Container inventory + topology)

Responsible for:
1. Creating RunJob entries for each task
2. Executing tasks sequentially
3. Managing artifact generation
4. Tracking token usage
5. Handling errors and status transitions
"""
from django.utils import timezone
from core.models import RunJob, RunArtifact
import logging

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Orchestrates execution of all task workers in a Run."""
    
    def create_run_jobs(self, run, jobs):
        """
        Create RunJob entries for all tasks in a run.
        
        CONTRACT:
        - Returns list of RunJob objects
        - Each RunJob initialized with status='pending'
        - Token counts initialized to 0
        """
        run_jobs = []
        for job in jobs:
            run_job = RunJob.objects.create(
                run=run,
                job=job,
                status="pending",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0
            )
            run_jobs.append(run_job)
        
        return run_jobs
    
    def execute_task(self, run_job):
        """
        Execute a single task (factory method dispatches to specific worker).
        
        CONTRACT:
        - Updates RunJob status: pending → running → success (or failed)
        - Records started_at and completed_at timestamps
        - Captures any errors in error_message field
        - Delegates to task-specific worker based on job.task_key
        """
        task_key = run_job.job.task_key
        
        # Mark as running
        run_job.status = "running"
        run_job.started_at = timezone.now()
        run_job.save()
        
        try:
            if task_key == "log_triage":
                from orchestration.task_workers import Task1LogTriageWorker
                worker = Task1LogTriageWorker()
                worker.execute(run_job)
            
            elif task_key == "gpu_report":
                from orchestration.task_workers import Task2GPUReportWorker
                worker = Task2GPUReportWorker()
                worker.execute(run_job)
            
            elif task_key == "service_map":
                from orchestration.task_workers import Task3ServiceMapWorker
                worker = Task3ServiceMapWorker()
                worker.execute(run_job)
            
            else:
                raise ValueError(f"Unknown task key: {task_key}")
            
            # Mark as success
            run_job.status = "success"
            run_job.completed_at = timezone.now()
            run_job.save()
            
        except Exception as e:
            # Mark as failed
            run_job.status = "failed"
            run_job.error_message = str(e)
            run_job.completed_at = timezone.now()
            run_job.save()
            
            logger.error(f"Task {task_key} failed: {e}")
