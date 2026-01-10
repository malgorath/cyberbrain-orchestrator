"""Test host selection with healthy non-stale hosts."""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta

from core.models import WorkerHost, Directive
from orchestrator.models import Directive as OrchestratorDirective


class HostSelectionForRunsTests(TestCase):
    """Tests for host selection in run launch."""
    
    def setUp(self):
        """Create test data."""
        self.client = APIClient()
        
        # Create orchestrator directive
        self.directive = OrchestratorDirective.objects.create(
            name='test-directive',
            description='Test directive'
        )
        
        # Create healthy, non-stale WorkerHost
        self.host = WorkerHost.objects.create(
            name='Test-Host',
            type='docker_socket',
            base_url='unix:///var/run/docker.sock',
            enabled=True,
            healthy=True,
            capabilities={},
            last_seen_at=timezone.now()  # Non-stale
        )
    
    def test_launch_run_with_healthy_host(self):
        """Launch should succeed with healthy non-stale host."""
        response = self.client.post('/api/runs/launch/', {
            'directive_id': self.directive.id,
            'tasks': ['log_triage'],
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn('id', data)
        
        # Verify run was created and assigned to host
        from orchestrator.models import Run
        run = Run.objects.get(id=data['id'])
        self.assertIsNotNone(run.worker_host)
        self.assertEqual(run.worker_host.id, self.host.id)
    
    def test_launch_fails_with_stale_host(self):
        """Launch should fail when only host is stale."""
        # Make host stale
        self.host.last_seen_at = timezone.now() - timedelta(minutes=10)
        self.host.save()
        
        response = self.client.post('/api/runs/launch/', {
            'directive_id': self.directive.id,
            'tasks': ['log_triage'],
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('error', data)
        self.assertIn('Host selection failed', data['error'])
    
    def test_launch_succeeds_after_heartbeat(self):
        """Launch should succeed after health endpoint updates last_seen_at."""
        # Make host stale first
        self.host.last_seen_at = timezone.now() - timedelta(minutes=10)
        self.host.save()
        
        # Access health endpoint to update heartbeat
        health_response = self.client.get(f'/api/worker-hosts/{self.host.id}/health/')
        self.assertEqual(health_response.status_code, status.HTTP_200_OK)
        
        # Verify host is no longer stale
        self.host.refresh_from_db()
        self.assertFalse(self.host.is_stale())
        
        # Now launch should succeed
        response = self.client.post('/api/runs/launch/', {
            'directive_id': self.directive.id,
            'tasks': ['log_triage'],
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
