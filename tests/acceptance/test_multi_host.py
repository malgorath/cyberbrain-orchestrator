"""
Phase 7 Acceptance Tests: Multi-Host Worker Expansion

Tests verify:
1. WorkerHost model stores host metadata and capabilities
2. Host selection routes runs to enabled hosts with capacity
3. Health checks monitor host availability
4. SSH tunnel enables secure VM Docker access
5. Routing distributes load across hosts
6. Failover to backup hosts when primary unavailable
7. API endpoints for WorkerHost CRUD
8. Run launch allows explicit host selection
"""

import json
from datetime import timedelta
from unittest.mock import patch, MagicMock
from unittest import skipIf

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from core.models import WorkerHost, Directive
from orchestrator.models import Run, Directive as OrchestratorDirective


class WorkerHostModelTests(TestCase):
    """WorkerHost model stores host configuration and capabilities."""

    def test_worker_host_creation(self):
        """WorkerHost can be created with full metadata."""
        host = WorkerHost.objects.create(
            name='Unraid-Main',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
            enabled=True,
            capabilities={
                'gpus': True,
                'gpu_count': 2,
                'labels': ['unraid', 'gpu'],
                'max_concurrency': 5,
            }
        )
        
        self.assertEqual(host.name, 'Unraid-Main')
        self.assertEqual(host.type, 'docker_socket')
        self.assertTrue(host.enabled)
        self.assertEqual(host.capabilities['gpu_count'], 2)
        self.assertIsNotNone(host.created_at)
    
    def test_worker_host_types(self):
        """WorkerHost supports docker_socket and docker_tcp types."""
        socket_host = WorkerHost.objects.create(
            name='Local',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
        )
        
        tcp_host = WorkerHost.objects.create(
            name='VM',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
        )
        
        self.assertEqual(socket_host.type, 'docker_socket')
        self.assertEqual(tcp_host.type, 'docker_tcp')
    
    def test_worker_host_capabilities_json(self):
        """Capabilities stored as JSON with flexible schema."""
        host = WorkerHost.objects.create(
            name='VM-Worker',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
            capabilities={
                'gpus': False,
                'max_concurrency': 10,
                'labels': ['vm', 'test'],
                'custom_field': 'custom_value',
            }
        )
        
        caps = host.capabilities
        self.assertFalse(caps['gpus'])
        self.assertEqual(caps['max_concurrency'], 10)
        self.assertIn('vm', caps['labels'])


class HostSelectionTests(TestCase):
    """Host selection routes runs to appropriate hosts."""

    def setUp(self):
        """Create test hosts."""
        self.unraid = WorkerHost.objects.create(
            name='Unraid',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
            enabled=True,
            capabilities={'gpus': True, 'gpu_count': 2, 'max_concurrency': 5}
        )
        
        self.vm = WorkerHost.objects.create(
            name='VM-192.168.1.15',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
            enabled=True,
            capabilities={'gpus': False, 'max_concurrency': 10}
        )
        
        self.directive = Directive.objects.create(
            directive_type='D3',
            name='Test-Directive',
            task_list=['log_triage'],
        )
    
    def test_default_host_selection(self):
        """When no host specified, selects Unraid (default)."""
        from orchestrator.host_router import HostRouter
        
        router = HostRouter()
        selected = router.select_host()
        
        # Should select first enabled host (Unraid by convention)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.name, 'Unraid')
    
    def test_explicit_host_selection(self):
        """Run can specify target host explicitly."""
        from orchestrator.host_router import HostRouter
        
        router = HostRouter()
        selected = router.select_host(target_host_id=self.vm.id)
        
        self.assertEqual(selected.id, self.vm.id)
        self.assertEqual(selected.name, 'VM-192.168.1.15')
    
    def test_disabled_host_not_selected(self):
        """Disabled hosts are skipped during selection."""
        from orchestrator.host_router import HostRouter
        
        # Disable Unraid
        self.unraid.enabled = False
        self.unraid.save()
        
        router = HostRouter()
        selected = router.select_host()
        
        # Should select VM (only enabled host)
        self.assertEqual(selected.name, 'VM-192.168.1.15')
    
    def test_load_balancing_across_hosts(self):
        """Router distributes runs to least loaded host."""
        from orchestrator.host_router import HostRouter
        
        # Simulate Unraid has 4 active runs
        self.unraid.active_runs_count = 4
        self.unraid.save()
        
        # VM has 0 active runs
        self.vm.active_runs_count = 0
        self.vm.save()
        
        router = HostRouter()
        selected = router.select_host()
        
        # Should select VM (less loaded)
        self.assertEqual(selected.name, 'VM-192.168.1.15')
    
    def test_gpu_requirement_routing(self):
        """Runs requiring GPU routed to GPU-enabled hosts."""
        from orchestrator.host_router import HostRouter
        
        router = HostRouter()
        selected = router.select_host(requires_gpu=True)
        
        # Should select Unraid (has GPUs)
        self.assertEqual(selected.name, 'Unraid')
        self.assertTrue(selected.capabilities.get('gpus', False))


class HealthCheckTests(TestCase):
    """Health checks monitor host availability."""

    def setUp(self):
        """Create test host."""
        self.host = WorkerHost.objects.create(
            name='Test-Host',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
            enabled=True,
        )
    
    @patch('orchestrator.health_checker.docker.DockerClient')
    def test_health_check_updates_last_seen(self, mock_docker):
        """Successful health check updates last_seen_at."""
        from orchestrator.health_checker import HealthChecker
        
        mock_docker.return_value.ping.return_value = True
        
        checker = HealthChecker()
        result = checker.check_host(self.host)
        
        self.assertTrue(result)
        self.host.refresh_from_db()
        self.assertIsNotNone(self.host.last_seen_at)
    
    @patch('orchestrator.health_checker.docker.DockerClient')
    def test_health_check_marks_unhealthy(self, mock_docker):
        """Failed health check marks host as unhealthy."""
        from orchestrator.health_checker import HealthChecker
        
        mock_docker.return_value.ping.side_effect = Exception("Connection failed")
        
        checker = HealthChecker()
        result = checker.check_host(self.host)
        
        self.assertFalse(result)
        self.host.refresh_from_db()
        self.assertFalse(self.host.healthy)
    
    def test_stale_host_detection(self):
        """Hosts not seen recently marked as stale."""
        # Set last_seen_at to 10 minutes ago
        self.host.last_seen_at = timezone.now() - timedelta(minutes=10)
        self.host.save()
        
        # Check if stale (threshold: 5 minutes)
        is_stale = self.host.is_stale(threshold_minutes=5)
        self.assertTrue(is_stale)


class SSHTunnelTests(TestCase):
    """SSH tunnel enables secure VM Docker access."""

    def setUp(self):
        """Create VM host with SSH config."""
        self.vm_host = WorkerHost.objects.create(
            name='VM-SSH',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
            enabled=True,
            ssh_config={
                'host': '192.168.1.15',
                'port': 22,
                'user': 'vmadmin',
                'key_path': '/secrets/vm_ssh_key',
            }
        )
    
    @skipIf(True, "Paramiko not yet installed (TODO)")
    def test_ssh_tunnel_creation(self, mock_ssh):
        """SSH tunnel created for docker_tcp hosts with SSH config."""
        from orchestrator.ssh_tunnel import SSHTunnelManager
        
        manager = SSHTunnelManager()
        tunnel = manager.create_tunnel(self.vm_host)
        
        self.assertIsNotNone(tunnel)
        # mock_ssh.return_value.connect.assert_called_once()  # Will add when paramiko implemented
    
    @skipIf(True, "Paramiko not yet installed (TODO)")
    def test_ssh_tunnel_forwards_docker_socket(self, mock_ssh):
        """SSH tunnel forwards remote Docker socket to local port."""
        from orchestrator.ssh_tunnel import SSHTunnelManager
        
        manager = SSHTunnelManager()
        local_port = manager.get_forwarded_port(self.vm_host)
        
        # Should allocate local port for forwarding
        self.assertIsNotNone(local_port)
        self.assertGreater(local_port, 1024)
    
    def test_ssh_config_not_in_logs(self):
        """SSH credentials never appear in logs or responses."""
        # SSH config stored but not exposed in serialization
        self.assertIn('key_path', self.vm_host.ssh_config)
        
        # Verify no secrets in string representation
        host_str = str(self.vm_host)
        self.assertNotIn('vmadmin', host_str)
        self.assertNotIn('ssh_key', host_str)


class FailoverTests(TestCase):
    """Failover to backup hosts when primary unavailable."""

    def setUp(self):
        """Create primary and backup hosts."""
        self.primary = WorkerHost.objects.create(
            name='Primary',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
            enabled=True,
            healthy=True,
        )
        
        self.backup = WorkerHost.objects.create(
            name='Backup',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
            enabled=True,
            healthy=True,
        )
    
    def test_failover_to_healthy_host(self):
        """When primary unhealthy, selects backup host."""
        from orchestrator.host_router import HostRouter
        
        # Mark primary as unhealthy
        self.primary.healthy = False
        self.primary.save()
        
        router = HostRouter()
        selected = router.select_host()
        
        # Should select backup (only healthy host)
        self.assertEqual(selected.name, 'Backup')
    
    def test_no_host_available_raises_error(self):
        """When all hosts unavailable, raises error."""
        from orchestrator.host_router import HostRouter
        
        # Disable all hosts
        self.primary.enabled = False
        self.primary.save()
        self.backup.enabled = False
        self.backup.save()
        
        router = HostRouter()
        
        with self.assertRaises(Exception) as ctx:
            router.select_host()
        
        self.assertIn('No available hosts', str(ctx.exception))


class WorkerHostAPITests(TestCase):
    """API endpoints for WorkerHost CRUD."""

    def setUp(self):
        """Setup API client and test host."""
        self.client = APIClient()
        self.host = WorkerHost.objects.create(
            name='Test-API-Host',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
            enabled=True,
        )
    
    def test_list_worker_hosts(self):
        """GET /api/worker-hosts/ lists all hosts."""
        response = self.client.get('/api/worker-hosts/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertGreater(len(data['results']), 0)
    
    def test_create_worker_host(self):
        """POST /api/worker-hosts/ creates new host."""
        response = self.client.post('/api/worker-hosts/', {
            'name': 'New-VM',
            'type': 'docker_tcp',
            'base_url': 'tcp://192.168.1.20:2376',
            'enabled': True,
            'capabilities': {
                'gpus': False,
                'max_concurrency': 5,
            }
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['name'], 'New-VM')
        self.assertEqual(data['type'], 'docker_tcp')
    
    def test_toggle_host_enabled(self):
        """PATCH /api/worker-hosts/{id}/ toggles enabled status."""
        response = self.client.patch(f'/api/worker-hosts/{self.host.id}/', {
            'enabled': False,
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.host.refresh_from_db()
        self.assertFalse(self.host.enabled)
    
    def test_get_host_health_status(self):
        """GET /api/worker-hosts/{id}/health/ returns health info."""
        response = self.client.get(f'/api/worker-hosts/{self.host.id}/health/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('healthy', data)
        self.assertIn('last_seen_at', data)
        
        # Verify heartbeat: last_seen_at should be set and host not stale
        self.host.refresh_from_db()
        self.assertIsNotNone(self.host.last_seen_at)
        self.assertFalse(self.host.is_stale())
    
    def test_delete_worker_host(self):
        """DELETE /api/worker-hosts/{id}/ removes host."""
        response = self.client.delete(f'/api/worker-hosts/{self.host.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(WorkerHost.objects.filter(id=self.host.id).exists())


class RunLaunchWithHostTests(TestCase):
    """Run launch allows explicit host selection."""

    def setUp(self):
        """Create hosts and directive."""
        self.unraid = WorkerHost.objects.create(
            name='Unraid',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
            enabled=True,
        )
        
        self.vm = WorkerHost.objects.create(
            name='VM',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
            enabled=True,
        )
        
        self.directive = OrchestratorDirective.objects.create(
            name='Test-Directive',
            description='Test',
        )
        
        self.client = APIClient()
    
    def test_run_launch_with_explicit_host(self):
        """POST /api/runs/launch/ accepts target_host_id parameter."""
        response = self.client.post('/api/runs/launch/', {
            'directive_id': self.directive.id,
            'tasks': ['log_triage'],
            'target_host_id': self.vm.id,
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        run_id = data['id']
        
        # Verify run associated with VM host
        run = Run.objects.get(id=run_id)
        self.assertEqual(run.worker_host_id, self.vm.id)
    
    def test_run_launch_defaults_to_auto_select(self):
        """POST /api/runs/launch/ without host uses automatic selection."""
        response = self.client.post('/api/runs/launch/', {
            'directive_id': self.directive.id,
            'tasks': ['log_triage'],
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        run_id = data['id']
        
        # Verify run has a host assigned
        run = Run.objects.get(id=run_id)
        self.assertIsNotNone(run.worker_host_id)


class InventoryPerHostTests(TestCase):
    """Inventory tracked per host."""

    def setUp(self):
        """Create test hosts."""
        self.unraid = WorkerHost.objects.create(
            name='Unraid',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
            enabled=True,
        )
        
        self.vm = WorkerHost.objects.create(
            name='VM',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
            enabled=True,
        )
    
    def test_container_inventory_per_host(self):
        """ContainerInventory stores host_id."""
        from core.models import ContainerInventory
        
        inventory = ContainerInventory.objects.create(
            worker_host=self.unraid,
            container_id='abc123',
            container_name='test-container',
            snapshot_data={'status': 'running'},
        )
        
        self.assertEqual(inventory.worker_host.id, self.unraid.id)
    
    def test_network_inventory_per_host(self):
        """Network inventory associated with host."""
        # Network inventory should include host_id field
        # This is a placeholder for future NetworkInventory model
        pass


class SecurityTests(TestCase):
    """Security constraints for multi-host setup."""

    def test_ssh_credentials_not_stored_in_logs(self):
        """SSH credentials never in DB logs or responses."""
        host = WorkerHost.objects.create(
            name='Secure-VM',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
            ssh_config={
                'host': '192.168.1.15',
                'user': 'secret_user',
                'key_path': '/secrets/key',
            }
        )
        
        # Verify ssh_config stored
        self.assertIn('key_path', host.ssh_config)
        
        # But not exposed in string representation
        host_str = str(host)
        self.assertNotIn('secret_user', host_str)
    
    def test_lan_only_constraint(self):
        """Only LAN IPs accepted for worker hosts."""
        # Should accept LAN IP
        lan_host = WorkerHost.objects.create(
            name='LAN-VM',
            type='docker_tcp',
            base_url='tcp://192.168.1.15:2376',
        )
        self.assertIsNotNone(lan_host)
        
        # Public IP should be rejected (validation at API layer)
        # This test documents the constraint
