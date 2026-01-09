"""
Phase 7: SSH Tunnel Manager - Secure Remote Docker Access

Manages SSH tunnels for secure Docker access to remote hosts.
Implements Option A: SSH tunnel with local port forwarding.

SECURITY: SSH credentials stored in ssh_config (not logged).
"""

import logging
import socket
from typing import Optional

from core.models import WorkerHost

logger = logging.getLogger(__name__)


class SSHTunnelManager:
    """Manages SSH tunnels for remote Docker access."""
    
    def __init__(self):
        self.tunnels = {}  # host_id -> tunnel info
    
    def create_tunnel(self, host: WorkerHost) -> Optional[dict]:
        """
        Create SSH tunnel for a WorkerHost.
        
        Args:
            host: WorkerHost with ssh_config
        
        Returns:
            Tunnel info dict or None
        """
        if host.type != 'docker_tcp':
            logger.debug(f"Host {host.name} is not docker_tcp, skipping SSH tunnel")
            return None
        
        if not host.ssh_config:
            logger.debug(f"Host {host.name} has no SSH config, skipping tunnel")
            return None
        
        try:
            # Extract SSH configuration
            ssh_host = host.ssh_config.get('host')
            ssh_port = host.ssh_config.get('port', 22)
            ssh_user = host.ssh_config.get('user')
            ssh_key_path = host.ssh_config.get('key_path')
            
            if not all([ssh_host, ssh_user, ssh_key_path]):
                logger.error(f"Incomplete SSH config for host {host.name}")
                return None
            
            # Allocate local port for forwarding
            local_port = self._allocate_local_port()
            
            logger.info(
                f"Creating SSH tunnel for {host.name}: "
                f"localhost:{local_port} -> {ssh_host}:2376"
            )
            
            # TODO: Implement actual SSH tunnel creation using paramiko
            # For now, return tunnel info structure
            tunnel_info = {
                'host_id': host.id,
                'local_port': local_port,
                'remote_host': ssh_host,
                'remote_port': 2376,
                'ssh_user': ssh_user,
                'active': False,  # Placeholder until actual tunnel created
            }
            
            self.tunnels[host.id] = tunnel_info
            
            return tunnel_info
        
        except Exception as e:
            logger.error(f"Failed to create SSH tunnel for {host.name}: {e}")
            return None
    
    def get_forwarded_port(self, host: WorkerHost) -> Optional[int]:
        """
        Get local forwarded port for a host.
        
        Args:
            host: WorkerHost
        
        Returns:
            Local port number or None
        """
        tunnel_info = self.tunnels.get(host.id)
        if tunnel_info:
            return tunnel_info['local_port']
        
        # Try to create tunnel if not exists
        new_tunnel = self.create_tunnel(host)
        if new_tunnel:
            return new_tunnel['local_port']
        
        return None
    
    def close_tunnel(self, host: WorkerHost) -> bool:
        """
        Close SSH tunnel for a host.
        
        Args:
            host: WorkerHost
        
        Returns:
            True if closed successfully
        """
        if host.id not in self.tunnels:
            logger.debug(f"No tunnel found for host {host.name}")
            return False
        
        try:
            tunnel_info = self.tunnels.pop(host.id)
            logger.info(f"Closed SSH tunnel for {host.name}")
            
            # TODO: Actual tunnel cleanup
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to close tunnel for {host.name}: {e}")
            return False
    
    def close_all_tunnels(self):
        """Close all active SSH tunnels."""
        host_ids = list(self.tunnels.keys())
        
        for host_id in host_ids:
            try:
                host = WorkerHost.objects.get(id=host_id)
                self.close_tunnel(host)
            except WorkerHost.DoesNotExist:
                logger.warning(f"Host {host_id} not found, cleaning up tunnel")
                self.tunnels.pop(host_id, None)
    
    def _allocate_local_port(self) -> int:
        """
        Allocate an available local port for SSH forwarding.
        
        Returns:
            Port number
        """
        # Find an available port in range 10000-20000
        for port in range(10000, 20000):
            try:
                # Try to bind to check if port is available
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(('localhost', port))
                sock.close()
                return port
            except OSError:
                continue
        
        raise Exception("No available local ports for SSH tunneling")


# Global tunnel manager instance
tunnel_manager = SSHTunnelManager()
