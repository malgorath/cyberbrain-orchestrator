"""
Worker orchestration module with Docker socket passthrough.

SECURITY CONTROLS:
- Worker image allowlist enforcement
- No host mounts except /logs and /uploads (read-only where possible)
- Full LAN network access (for now)
- Per-task ephemeral workers
- GPU scheduling with VRAM-aware selection
- CPU fallback when VRAM insufficient
- Audit trail for all worker operations
"""
import docker
import logging
from typing import Optional, Dict, List, Tuple
from django.conf import settings
from django.utils import timezone
from core.models import (
    WorkerImageAllowlist, WorkerAudit, GPUState, RunJob
)

logger = logging.getLogger(__name__)


class WorkerOrchestrator:
    """
    Orchestrates ephemeral Docker worker containers with GPU scheduling.
    """
    
    def __init__(self):
        """Initialize Docker client with socket passthrough"""
        try:
            # Use Docker socket at /var/run/docker.sock
            self.docker_client = docker.from_env()
            logger.info("Worker orchestrator initialized with Docker socket")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.docker_client = None
    
    def _is_image_allowed(self, image_name: str, image_tag: str = 'latest') -> Tuple[bool, Optional[WorkerImageAllowlist]]:
        """
        Check if Docker image is in allowlist.
        
        Returns:
            Tuple of (is_allowed, allowlist_entry)
        """
        try:
            entry = WorkerImageAllowlist.objects.get(
                image_name=image_name,
                image_tag=image_tag,
                is_active=True
            )
            return True, entry
        except WorkerImageAllowlist.DoesNotExist:
            logger.warning(f"Image not in allowlist: {image_name}:{image_tag}")
            return False, None
    
    def _select_gpu(
        self,
        min_vram_mb: int = 0,
        explicit_gpu: Optional[str] = None
    ) -> Tuple[Optional[str], str]:
        """
        Select GPU using weighted blend scheduling.
        
        Args:
            min_vram_mb: Minimum VRAM required
            explicit_gpu: Explicit GPU override (e.g., '0', '1')
        
        Returns:
            Tuple of (gpu_id or None for CPU, selection_reason)
        """
        # Handle explicit GPU override
        if explicit_gpu is not None:
            try:
                gpu = GPUState.objects.get(gpu_id=explicit_gpu, is_available=True)
                if gpu.free_vram_mb >= min_vram_mb:
                    reason = f"Explicit override to GPU {explicit_gpu}"
                    logger.info(reason)
                    return explicit_gpu, reason
                else:
                    reason = f"Explicit GPU {explicit_gpu} insufficient VRAM ({gpu.free_vram_mb}MB < {min_vram_mb}MB required), falling back to auto-select"
                    logger.warning(reason)
            except GPUState.DoesNotExist:
                reason = f"Explicit GPU {explicit_gpu} not found, falling back to auto-select"
                logger.warning(reason)
        
        # Get available GPUs
        gpus = GPUState.objects.filter(is_available=True).order_by('gpu_id')
        
        if not gpus.exists():
            reason = "No GPUs available, using CPU fallback"
            logger.warning(reason)
            return None, reason
        
        # Filter by VRAM requirement
        suitable_gpus = [gpu for gpu in gpus if gpu.free_vram_mb >= min_vram_mb]
        
        if not suitable_gpus:
            reason = f"No GPUs with sufficient VRAM ({min_vram_mb}MB required), using CPU fallback"
            logger.warning(reason)
            return None, reason
        
        # Select GPU with lowest scheduling score (most idle)
        # Weighted blend: 60% VRAM headroom + 40% utilization
        best_gpu = min(suitable_gpus, key=lambda g: g.scheduling_score)
        
        reason = (
            f"Selected GPU {best_gpu.gpu_id} - "
            f"{best_gpu.free_vram_mb}MB free VRAM ({best_gpu.free_vram_mb / best_gpu.total_vram_mb * 100:.1f}% headroom), "
            f"{best_gpu.utilization_percent:.1f}% utilization, "
            f"{best_gpu.active_workers} active workers"
        )
        logger.info(reason)
        
        return best_gpu.gpu_id, reason
    
    def _build_container_config(
        self,
        image_name: str,
        image_tag: str,
        gpu_id: Optional[str],
        run_job: RunJob,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Dict:
        """
        Build Docker container configuration with security controls.
        
        SECURITY CONTROLS:
        - Only mount /logs and /uploads
        - Use full LAN network
        - Set resource limits
        - Apply GPU device requests if GPU assigned
        """
        config = {
            'image': f"{image_name}:{image_tag}",
            'detach': True,
            'remove': True,  # Ephemeral - auto-remove when stopped
            'network_mode': 'bridge',  # Full LAN network
            'environment': env_vars or {},
            'volumes': {
                # Mount logs and uploads (read-only where appropriate)
                settings.CYBER_BRAIN_LOGS: {
                    'bind': '/logs',
                    'mode': 'rw'  # Workers may need to write logs
                },
                settings.CYBER_BRAIN_UPLOADS: {
                    'bind': '/uploads',
                    'mode': 'ro'  # Read-only access to uploads
                }
            },
            'labels': {
                'cyberbrain.run_job_id': str(run_job.id),
                'cyberbrain.run_id': str(run_job.run.id),
                'cyberbrain.task_type': run_job.job.task_type,
                'cyberbrain.ephemeral': 'true'
            }
        }
        
        # Add GPU device if assigned
        if gpu_id is not None:
            config['device_requests'] = [
                docker.types.DeviceRequest(
                    device_ids=[gpu_id],
                    capabilities=[['gpu']]
                )
            ]
        
        # Add resource limits
        config['mem_limit'] = '4g'  # 4GB memory limit
        config['memswap_limit'] = '4g'  # No swap
        
        return config
    
    def spawn_worker(
        self,
        run_job: RunJob,
        image_name: str,
        image_tag: str = 'latest',
        explicit_gpu: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Optional[str], str]:
        """
        Spawn an ephemeral worker container for a run job.
        
        Args:
            run_job: RunJob to execute
            image_name: Docker image name
            image_tag: Docker image tag
            explicit_gpu: Explicit GPU override
            env_vars: Additional environment variables
        
        Returns:
            Tuple of (success, container_id, message)
        """
        if not self.docker_client:
            msg = "Docker client not initialized"
            logger.error(msg)
            self._audit(run_job, 'error', None, image_name, None, msg, False, msg)
            return False, None, msg
        
        # Check image allowlist
        is_allowed, allowlist_entry = self._is_image_allowed(image_name, image_tag)
        if not is_allowed:
            msg = f"Image not in allowlist: {image_name}:{image_tag}"
            logger.error(msg)
            self._audit(run_job, 'error', None, f"{image_name}:{image_tag}", None, msg, False, msg)
            return False, None, msg
        
        # Select GPU
        gpu_id, gpu_reason = self._select_gpu(
            min_vram_mb=allowlist_entry.min_vram_mb if allowlist_entry.requires_gpu else 0,
            explicit_gpu=explicit_gpu
        )
        
        # Build container configuration
        config = self._build_container_config(
            image_name,
            image_tag,
            gpu_id,
            run_job,
            env_vars
        )
        
        try:
            # Spawn container
            logger.info(f"Spawning worker for RunJob {run_job.id} with image {image_name}:{image_tag}")
            container = self.docker_client.containers.run(**config)
            container_id = container.id
            
            # Update GPU state
            if gpu_id is not None:
                gpu = GPUState.objects.get(gpu_id=gpu_id)
                gpu.active_workers += 1
                gpu.save()
            
            # Audit log
            self._audit(
                run_job,
                'spawn',
                container_id,
                f"{image_name}:{image_tag}",
                gpu_id or 'cpu',
                gpu_reason,
                True,
                ""
            )
            
            msg = f"Worker spawned: {container_id[:12]}"
            logger.info(msg)
            return True, container_id, msg
            
        except Exception as e:
            msg = f"Failed to spawn worker: {str(e)}"
            logger.error(msg)
            self._audit(run_job, 'error', None, f"{image_name}:{image_tag}", 
                       gpu_id or 'cpu', gpu_reason, False, msg)
            return False, None, msg
    
    def stop_worker(self, container_id: str, run_job: Optional[RunJob] = None) -> Tuple[bool, str]:
        """
        Stop and remove a worker container.
        
        Args:
            container_id: Container ID
            run_job: Optional RunJob for audit trail
        
        Returns:
            Tuple of (success, message)
        """
        if not self.docker_client:
            msg = "Docker client not initialized"
            logger.error(msg)
            return False, msg
        
        try:
            container = self.docker_client.containers.get(container_id)
            
            # Get GPU from labels
            labels = container.labels
            gpu_id = labels.get('cyberbrain.gpu_id')
            
            # Stop container
            container.stop(timeout=10)
            container.remove()
            
            # Update GPU state
            if gpu_id and gpu_id != 'cpu':
                try:
                    gpu = GPUState.objects.get(gpu_id=gpu_id)
                    gpu.active_workers = max(0, gpu.active_workers - 1)
                    gpu.save()
                except GPUState.DoesNotExist:
                    pass
            
            # Audit log
            if run_job:
                self._audit(run_job, 'stop', container_id, container.image.tags[0] if container.image.tags else 'unknown',
                           gpu_id or 'cpu', "Worker stopped", True, "")
            
            msg = f"Worker stopped: {container_id[:12]}"
            logger.info(msg)
            return True, msg
            
        except Exception as e:
            msg = f"Failed to stop worker: {str(e)}"
            logger.error(msg)
            if run_job:
                self._audit(run_job, 'error', container_id, 'unknown', 'unknown', 
                           "Stop failed", False, msg)
            return False, msg
    
    def _audit(
        self,
        run_job: Optional[RunJob],
        operation: str,
        container_id: Optional[str],
        image_name: str,
        gpu_assigned: Optional[str],
        gpu_reason: str,
        success: bool,
        error_message: str
    ):
        """Create audit entry for worker operation"""
        try:
            WorkerAudit.objects.create(
                run_job=run_job,
                operation=operation,
                container_id=container_id or '',
                image_name=image_name,
                gpu_assigned=gpu_assigned or '',
                gpu_selection_reason=gpu_reason,
                config_snapshot={},  # Could add more details here
                success=success,
                error_message=error_message
            )
        except Exception as e:
            logger.error(f"Failed to create audit entry: {e}")
    
    def list_active_workers(self) -> List[Dict]:
        """
        List all active cyberbrain worker containers.
        
        Returns:
            List of worker dictionaries with status
        """
        if not self.docker_client:
            return []
        
        try:
            filters = {'label': 'cyberbrain.ephemeral=true'}
            containers = self.docker_client.containers.list(filters=filters)
            
            workers = []
            for container in containers:
                workers.append({
                    'container_id': container.id,
                    'short_id': container.short_id,
                    'image': container.image.tags[0] if container.image.tags else 'unknown',
                    'status': container.status,
                    'run_job_id': container.labels.get('cyberbrain.run_job_id'),
                    'task_type': container.labels.get('cyberbrain.task_type'),
                    'created': container.attrs['Created']
                })
            
            return workers
            
        except Exception as e:
            logger.error(f"Failed to list workers: {e}")
            return []
    
    def cleanup_orphaned_workers(self) -> int:
        """
        Clean up orphaned worker containers.
        
        Returns:
            Number of containers cleaned up
        """
        if not self.docker_client:
            return 0
        
        try:
            filters = {'label': 'cyberbrain.ephemeral=true', 'status': 'exited'}
            containers = self.docker_client.containers.list(all=True, filters=filters)
            
            count = 0
            for container in containers:
                try:
                    container.remove()
                    count += 1
                    logger.info(f"Removed orphaned worker: {container.short_id}")
                except Exception as e:
                    logger.error(f"Failed to remove orphaned worker {container.short_id}: {e}")
            
            return count
            
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned workers: {e}")
            return 0


def update_gpu_states():
    """
    Update GPU state information for scheduling.
    Should be called periodically (e.g., every 30 seconds).
    """
    try:
        # This would typically use nvidia-smi or similar
        # For now, just a placeholder
        # In production, parse nvidia-smi output or use pynvml
        logger.info("GPU state update triggered (placeholder)")
        pass
    except Exception as e:
        logger.error(f"Failed to update GPU states: {e}")
