"""
Real Docker Log Collector Implementation

Connects to Docker socket and collects actual container logs.
Respects ContainerAllowlist and handles errors gracefully.

CONTRACT:
- Only allowlisted containers can be accessed
- Logs filtered by timestamp (since last run)
- Errors handled without crashing
- UTF-8 encoding enforced
"""
import docker
from docker.errors import DockerException, NotFound
from django.utils import timezone
from core.models import ContainerAllowlist, RunJob
import logging

logger = logging.getLogger(__name__)


class DockerLogCollector:
    """Collects logs from Docker containers via socket."""
    
    def __init__(self):
        self._client = None
    
    def get_client(self):
        """
        Get Docker client connected to socket.
        
        CONTRACT:
        - Returns docker.DockerClient
        - Raises DockerException if socket unavailable
        """
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as e:
                logger.error(f"Failed to connect to Docker socket: {e}")
                raise
        
        return self._client
    
    def collect_logs(self, container_id, since=None, tail=1000):
        """
        Collect logs from a container.
        
        CONTRACT:
        - container_id must be in ContainerAllowlist with enabled=True
        - Returns string of log entries
        - Returns empty string if container not found
        - Raises PermissionError if container not allowlisted
        
        Args:
            container_id: Docker container ID
            since: datetime to filter logs (optional)
            tail: Number of lines to retrieve (default 1000)
        
        Returns:
            String of log entries (UTF-8 decoded)
        """
        # Check allowlist
        if not self._is_allowed(container_id):
            raise PermissionError(
                f"Container {container_id} not in allowlist or disabled"
            )
        
        try:
            client = self.get_client()
            container = client.containers.get(container_id)
            
            # Collect logs with parameters
            kwargs = {'tail': tail, 'timestamps': True}
            if since:
                kwargs['since'] = since
            
            log_bytes = container.logs(**kwargs)
            
            # Decode to string
            try:
                logs = log_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # Fall back to latin-1 if UTF-8 fails
                logs = log_bytes.decode('latin-1', errors='replace')
            
            return logs
        
        except NotFound:
            logger.warning(f"Container {container_id} not found")
            return ""
        
        except DockerException as e:
            logger.error(f"Docker error collecting logs: {e}")
            return ""
    
    def collect_logs_since_last_run(self, container_id, job):
        """
        Collect logs since last successful run of this job.
        
        CONTRACT:
        - Returns logs since last successful RunJob completion
        - Returns all logs if no previous successful run
        
        Args:
            container_id: Docker container ID
            job: Job model instance
        
        Returns:
            String of log entries
        """
        since = self.get_last_successful_run_time(job)
        return self.collect_logs(container_id, since=since)
    
    def get_last_successful_run_time(self, job):
        """
        Get timestamp of last successful run for this job.
        
        CONTRACT:
        - Returns datetime of last successful RunJob completion
        - Returns None if no previous successful runs
        
        Args:
            job: Job model instance
        
        Returns:
            datetime or None
        """
        last_run_job = RunJob.objects.filter(
            job=job,
            status="success"
        ).order_by('-completed_at').first()
        
        if last_run_job and last_run_job.completed_at:
            return last_run_job.completed_at
        
        return None
    
    def _is_allowed(self, container_id):
        """Check if container is in allowlist and enabled."""
        return ContainerAllowlist.objects.filter(
            container_id=container_id,
            enabled=True
        ).exists()
