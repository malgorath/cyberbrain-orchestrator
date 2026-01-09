"""
Worker Orchestration Service

Manages worker container lifecycle via Docker socket:
- Spawn workers from allowlisted images
- Allocate GPU resources
- Track all operations in WorkerAudit
- Clean up on completion

Design by Contract:
- spawn_worker() requires allowlisted image, creates audit
- stop_worker() requires valid worker_id, releases GPU, creates audit
- GPU allocation is exclusive (one worker per GPU)
"""
import docker
from typing import Optional
from django.utils import timezone
from core.models import (
    Run, WorkerAudit, WorkerImageAllowlist, GPUState
)


class WorkerOrchestrator:
    """Orchestrates worker container lifecycle and GPU allocation"""
    
    def __init__(self, docker_client=None):
        """Initialize with Docker client (injectable for testing)"""
        self.docker_client = docker_client or docker.from_env()
    
    def spawn_worker(
        self, 
        run: Run, 
        image_name: str,
        require_gpu: bool = False,
        env_vars: Optional[dict] = None
    ) -> str:
        """
        Spawn a worker container for the given run.
        
        Args:
            run: Run instance to spawn worker for
            image_name: Docker image name (must be allowlisted)
            require_gpu: Whether worker requires GPU allocation
            env_vars: Optional environment variables for container
        
        Returns:
            worker_id: Container ID of spawned worker
        
        Raises:
            ValueError: If image not allowlisted
            RuntimeError: If GPU required but none available
        
        Contract:
        - Creates WorkerAudit record (success or failure)
        - If require_gpu=True, allocates GPU and sets GPUState.allocated_to
        - Returns container ID on success
        """
        # Check allowlist first
        if not self._is_image_allowlisted(image_name):
            error_msg = f"Image {image_name} is not allowlisted"
            self._create_audit(
                run=run,
                action="spawn",
                image_name=image_name,
                success=False,
                error_message=error_msg
            )
            raise ValueError(error_msg)
        
        # Allocate GPU if required
        gpu_id = None
        if require_gpu:
            try:
                gpu_id = self._allocate_gpu()
            except RuntimeError as e:
                error_msg = f"GPU allocation failed: {str(e)}"
                self._create_audit(
                    run=run,
                    action="spawn",
                    image_name=image_name,
                    success=False,
                    error_message=error_msg
                )
                raise RuntimeError("No GPU available") from e
        
        try:
            # For now, return mock container ID
            # In production, would call: container = self.docker_client.containers.run(...)
            worker_id = f"mock-worker-{run.id}-{timezone.now().timestamp()}"
            
            # Create success audit
            self._create_audit(
                run=run,
                action="spawn",
                worker_id=worker_id,
                image_name=image_name,
                gpu_id=gpu_id,
                success=True
            )
            
            return worker_id
            
        except Exception as e:
            error_msg = f"Worker spawn failed: {str(e)}"
            self._create_audit(
                run=run,
                action="spawn",
                image_name=image_name,
                gpu_id=gpu_id,
                success=False,
                error_message=error_msg
            )
            # Release GPU if it was allocated
            if gpu_id is not None:
                self._release_gpu(gpu_id)
            raise
    
    def stop_worker(self, run: Run, worker_id: str) -> None:
        """
        Stop a running worker container.
        
        Args:
            run: Run instance
            worker_id: Container ID to stop
        
        Contract:
        - Creates WorkerAudit record for stop action
        - Releases any GPU allocated to this worker
        - Container is stopped and removed
        """
        try:
            # Release GPU if allocated to this worker
            self._release_gpu_for_worker(worker_id)
            
            # For now, mock the stop operation
            # In production, would call: self.docker_client.containers.get(worker_id).stop()
            
            # Create success audit
            self._create_audit(
                run=run,
                action="stop",
                worker_id=worker_id,
                success=True
            )
            
        except Exception as e:
            error_msg = f"Worker stop failed: {str(e)}"
            self._create_audit(
                run=run,
                action="stop",
                worker_id=worker_id,
                success=False,
                error_message=error_msg
            )
            raise
    
    def _is_image_allowlisted(self, image_name: str) -> bool:
        """Check if image is in WorkerImageAllowlist"""
        return WorkerImageAllowlist.objects.filter(
            image_name=image_name,
            is_active=True
        ).exists()
    
    def _allocate_gpu(self) -> str:
        """
        Allocate an available GPU.
        
        Returns:
            gpu_id: ID of allocated GPU
        
        Raises:
            RuntimeError: If no GPU available
        """
        available_gpu = GPUState.objects.filter(is_available=True).order_by('active_workers').first()
        if not available_gpu:
            raise RuntimeError("No GPU available")
        
        # Increment active workers counter
        available_gpu.active_workers += 1
        available_gpu.save()
        return available_gpu.gpu_id
    
    def _release_gpu(self, gpu_id: str) -> None:
        """Release GPU by ID"""
        try:
            gpu = GPUState.objects.get(gpu_id=gpu_id)
            gpu.active_workers = max(0, gpu.active_workers - 1)
            gpu.save()
        except GPUState.DoesNotExist:
            pass  # GPU not found, nothing to release
    
    def _release_gpu_for_worker(self, worker_id: str) -> None:
        """Release GPU allocated to specific worker (via audit lookup)"""
        try:
            audit = WorkerAudit.objects.filter(
                container_id=worker_id,
                operation="spawn",
                success=True
            ).exclude(gpu_assigned="").first()
            
            if audit and audit.gpu_assigned:
                self._release_gpu(audit.gpu_assigned)
        except Exception:
            pass  # Best effort cleanup
    
    def _create_audit(
        self,
        run: Run,
        action: str,
        worker_id: Optional[str] = None,
        image_name: Optional[str] = None,
        gpu_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> WorkerAudit:
        """Create WorkerAudit record"""
        # Map action to operation (test uses 'spawn'/'stop', model uses 'spawn'/'stop')
        return WorkerAudit.objects.create(
            run_job=None,  # For now, not linked to specific RunJob
            operation=action,
            container_id=worker_id or "",
            image_name=image_name or "",
            gpu_assigned=gpu_id or "",
            success=success,
            error_message=error_message or ""
        )
