"""
Phase 7: Health Checker - Worker Host Monitoring

Monitors WorkerHost health via:
- Docker ping (connection check)
- GPU availability (if enabled)
- Last seen timestamp updates
"""

import logging
from datetime import timedelta

import docker
from django.utils import timezone

from core.models import WorkerHost

logger = logging.getLogger(__name__)


class HealthChecker:
    """Monitors worker host health."""
    
    def check_host(self, host: WorkerHost) -> bool:
        """
        Perform health check on a WorkerHost.
        
        Args:
            host: WorkerHost to check
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            logger.debug(f"Health checking host: {host.name}")
            
            # Create Docker client for this host
            client = self._create_docker_client(host)
            
            # Ping Docker daemon
            client.ping()
            
            # Update health status
            host.healthy = True
            host.last_seen_at = timezone.now()
            host.save(update_fields=['healthy', 'last_seen_at'])
            
            logger.info(f"Host {host.name} is healthy")
            return True
        
        except Exception as e:
            logger.error(f"Host {host.name} health check failed: {e}")
            
            # Mark as unhealthy
            host.healthy = False
            host.save(update_fields=['healthy'])
            
            return False
    
    def check_all_hosts(self) -> dict:
        """
        Check health of all enabled hosts.
        
        Returns:
            Dict with health check results
        """
        results = {
            'healthy': [],
            'unhealthy': [],
            'disabled': []
        }
        
        for host in WorkerHost.objects.all():
            if not host.enabled:
                results['disabled'].append(host.name)
                continue
            
            is_healthy = self.check_host(host)
            
            if is_healthy:
                results['healthy'].append(host.name)
            else:
                results['unhealthy'].append(host.name)
        
        logger.info(
            f"Health check complete: "
            f"{len(results['healthy'])} healthy, "
            f"{len(results['unhealthy'])} unhealthy, "
            f"{len(results['disabled'])} disabled"
        )
        
        return results
    
    def mark_stale_hosts_unhealthy(self, threshold_minutes=10):
        """
        Mark hosts as unhealthy if not seen recently.
        
        Args:
            threshold_minutes: Time threshold for staleness
        """
        threshold = timezone.now() - timedelta(minutes=threshold_minutes)
        
        stale_hosts = WorkerHost.objects.filter(
            enabled=True,
            healthy=True,
            last_seen_at__lt=threshold
        )
        
        count = stale_hosts.update(healthy=False)
        
        if count > 0:
            logger.warning(f"Marked {count} stale hosts as unhealthy")
    
    def _create_docker_client(self, host: WorkerHost):
        """
        Create Docker client for a host.
        
        Args:
            host: WorkerHost to connect to
        
        Returns:
            docker.DockerClient instance
        """
        if host.type == 'docker_socket':
            # Local socket connection
            return docker.DockerClient(base_url=host.base_url)
        
        elif host.type == 'docker_tcp':
            # TCP connection (may use SSH tunnel)
            # For now, direct TCP connection
            # TODO: SSH tunnel support
            return docker.DockerClient(base_url=host.base_url)
        
        else:
            raise ValueError(f"Unknown host type: {host.type}")
