"""
Phase 7: Host Router - Worker Host Selection

Selects appropriate WorkerHost for task execution based on:
- Enabled/healthy status
- Available capacity
- GPU requirements
- Explicit host override
- Load balancing across hosts
"""

import logging
from typing import Optional

from core.models import WorkerHost

logger = logging.getLogger(__name__)


class HostRouter:
    """Routes runs to appropriate worker hosts."""
    
    def select_host(
        self,
        target_host_id: Optional[int] = None,
        requires_gpu: bool = False
    ) -> WorkerHost:
        """
        Select a WorkerHost for task execution.
        
        Args:
            target_host_id: Explicit host ID (overrides auto-selection)
            requires_gpu: Whether task requires GPU access
        
        Returns:
            WorkerHost instance
        
        Raises:
            Exception: If no suitable host available
        """
        # Explicit host selection
        if target_host_id:
            try:
                host = WorkerHost.objects.get(id=target_host_id)
                if not host.is_available():
                    logger.warning(f"Target host {host.name} not available, selecting alternative")
                else:
                    logger.info(f"Using explicit target host: {host.name}")
                    return host
            except WorkerHost.DoesNotExist:
                logger.error(f"Target host ID {target_host_id} not found")
        
        # Auto-selection: filter available hosts
        all_hosts = WorkerHost.objects.all()
        available_hosts = []
        
        # Diagnostic: track why hosts are excluded
        excluded_reasons = []
        
        for host in all_hosts:
            reasons = []
            if not host.enabled:
                reasons.append('disabled')
            if not host.healthy:
                reasons.append('unhealthy')
            if host.is_stale():
                reasons.append('stale')
            if requires_gpu and not host.has_gpu():
                reasons.append('no_gpu')
            
            if reasons:
                excluded_reasons.append(f"{host.name}(id={host.id}): {','.join(reasons)}")
            else:
                available_hosts.append(host)
        
        if not available_hosts:
            logger.error(
                f"Host selection failed. Total hosts: {all_hosts.count()}, "
                f"Excluded: {'; '.join(excluded_reasons) if excluded_reasons else 'none'}"
            )
            raise Exception("No available hosts found. All hosts are disabled or unhealthy.")
        
        # Select host with most available capacity
        # Sort by: has_capacity (True first), then fewest active_runs
        available_hosts.sort(key=lambda h: (not h.has_capacity(), h.active_runs_count))
        
        selected = available_hosts[0]
        logger.info(
            f"Selected host: {selected.name} "
            f"(runs: {selected.active_runs_count}, "
            f"gpu: {selected.has_gpu()})"
        )
        
        return selected
    
    def get_default_host(self) -> Optional[WorkerHost]:
        """
        Get the default WorkerHost (typically Unraid local host).
        
        Returns:
            First enabled docker_socket host, or None
        """
        default = WorkerHost.objects.filter(
            type='docker_socket',
            enabled=True,
            healthy=True
        ).first()
        
        if default:
            logger.debug(f"Default host: {default.name}")
        else:
            logger.warning("No default docker_socket host available")
        
        return default
    
    def increment_active_runs(self, host: WorkerHost) -> None:
        """Increment active run counter for a host."""
        host.active_runs_count += 1
        host.save(update_fields=['active_runs_count'])
        logger.debug(f"Host {host.name} active runs: {host.active_runs_count}")
    
    def decrement_active_runs(self, host: WorkerHost) -> None:
        """Decrement active run counter for a host."""
        if host.active_runs_count > 0:
            host.active_runs_count -= 1
            host.save(update_fields=['active_runs_count'])
            logger.debug(f"Host {host.name} active runs: {host.active_runs_count}")
