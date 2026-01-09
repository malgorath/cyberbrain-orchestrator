"""
Acceptance tests for enhanced API endpoints (Task 6).

Tests:
- /api/runs/since-last-success/  (since last successful run queries)
- /api/container-inventory/      (container allowlist + inventory)
"""

import json
from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta

from core.models import Directive, Job, Run, ContainerAllowlist, ContainerInventory, LLMCall
from orchestrator.models import Directive as LegacyDirective


class EnhancedAPIEndpointsTests(TestCase):
    """Test enhanced API endpoints"""
    
    def setUp(self):
        self.client = Client()
        self.client.defaults['HTTP_ACCEPT'] = 'application/json'
        
        # Create test directive and jobs
        self.directive = Directive.objects.create(
            directive_type='D1',
            name='Test Directive',
            description='For testing'
        )
        
        self.job = Job.objects.create(
            task_key='log_triage',
            name='Log Triage Job',
            default_directive=self.directive
        )
    
    def test_since_last_success_no_runs(self):
        """Test /api/runs/since-last-success/ with no runs"""
        response = self.client.get('/api/runs/since-last-success/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIsNone(data['last_success_run'])
        self.assertEqual(data['total_count'], 0)
        self.assertEqual(len(data['runs_since']), 0)
    
    def test_since_last_success_with_single_success(self):
        """Test /api/runs/since-last-success/ with one successful run"""
        # Create a successful run
        now = timezone.now()
        run = Run.objects.create(
            job=self.job,
            status='success',
            started_at=now - timedelta(hours=1),
            ended_at=now - timedelta(minutes=30),
        )
        
        response = self.client.get('/api/runs/since-last-success/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIsNotNone(data['last_success_run'])
        self.assertEqual(data['last_success_run']['id'], run.id)
        self.assertEqual(data['last_success_run']['status'], 'success')
        self.assertEqual(data['total_count'], 0)  # No runs after this one
    
    def test_since_last_success_with_multiple_runs(self):
        """Test /api/runs/since-last-success/ with multiple runs"""
        now = timezone.now()
        
        # Create successful run
        success_run = Run.objects.create(
            job=self.job,
            status='success',
            started_at=now - timedelta(hours=2),
            ended_at=now - timedelta(hours=1, minutes=30),
        )
        
        # Create runs after the successful run
        pending_run = Run.objects.create(
            job=self.job,
            status='pending',
            started_at=now - timedelta(minutes=45),
            ended_at=None,
        )
        
        failed_run = Run.objects.create(
            job=self.job,
            status='failed',
            started_at=now - timedelta(minutes=30),
            ended_at=now - timedelta(minutes=10),
        )
        
        response = self.client.get('/api/runs/since-last-success/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['last_success_run']['id'], success_run.id)
        self.assertEqual(data['total_count'], 2)  # pending + failed
        
        run_ids = [run['id'] for run in data['runs_since']]
        self.assertIn(pending_run.id, run_ids)
        self.assertIn(failed_run.id, run_ids)
    
    def test_container_inventory_empty(self):
        """Test /api/container-inventory/ with no containers"""
        response = self.client.get('/api/container-inventory/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['allowlist_count'], 0)
        self.assertEqual(len(data['allowlist']), 0)
        self.assertEqual(data['total_snapshots'], 0)
    
    def test_container_inventory_with_allowlist(self):
        """Test /api/container-inventory/ with allowlist entries"""
        # Create allowlist entries
        ContainerAllowlist.objects.create(
            container_id='abc123',
            container_name='test-container-1',
            enabled=True,
            description='Test container 1'
        )
        
        ContainerAllowlist.objects.create(
            container_id='def456',
            container_name='test-container-2',
            enabled=True,
            description='Test container 2'
        )
        
        # Create a disabled entry (should not appear)
        ContainerAllowlist.objects.create(
            container_id='xyz789',
            container_name='disabled-container',
            enabled=False,
        )
        
        response = self.client.get('/api/container-inventory/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['allowlist_count'], 2)  # Only enabled
        self.assertEqual(len(data['allowlist']), 2)
        
        container_names = [c['container_name'] for c in data['allowlist']]
        self.assertIn('test-container-1', container_names)
        self.assertIn('test-container-2', container_names)
        self.assertNotIn('disabled-container', container_names)
    
    def test_container_inventory_with_snapshots(self):
        """Test /api/container-inventory/ with snapshots"""
        # Create a run
        now = timezone.now()
        run = Run.objects.create(
            job=self.job,
            status='running',
            started_at=now,
        )
        
        # Create container inventory snapshots
        for i in range(5):
            ContainerInventory.objects.create(
                container_id=f'container_{i}',
                container_name=f'container-{i}',
                snapshot_data={'status': 'running', 'image': f'image-{i}'},
                run=run if i == 0 else None,
                created_at=now - timedelta(minutes=5-i)
            )
        
        response = self.client.get('/api/container-inventory/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['total_snapshots'], 5)
        self.assertEqual(len(data['recent_snapshots']), 5)  # All 5 are recent
        
        # Verify ordering (newest first)
        names = [s['container_name'] for s in data['recent_snapshots']]
        self.assertEqual(names[0], 'container-4')  # Most recent
        self.assertEqual(names[-1], 'container-0')  # Oldest of these 5
    
    def test_container_inventory_snapshot_limit(self):
        """Test /api/container-inventory/ limits snapshots to 10 recent"""
        # Create 15 snapshots
        now = timezone.now()
        for i in range(15):
            ContainerInventory.objects.create(
                container_id=f'container_{i}',
                container_name=f'container-{i}',
                snapshot_data={'status': 'running'},
                created_at=now - timedelta(minutes=15-i)
            )
        
        response = self.client.get('/api/container-inventory/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['total_snapshots'], 15)
        self.assertEqual(len(data['recent_snapshots']), 10)  # Limited to 10 most recent


class SinceLastSuccessQueryTests(TestCase):
    """Test 'since last successful run' query functionality"""
    
    def setUp(self):
        self.client = Client()
        self.directive = Directive.objects.create(
            directive_type='D1',
            name='Test Directive'
        )
        self.job = Job.objects.create(
            task_key='log_triage',
            name='Job',
            default_directive=self.directive
        )
    
    def test_scenario_success_then_failures(self):
        """Scenario: One success, then some failures/pending after"""
        now = timezone.now()
        
        # Initial success
        success = Run.objects.create(
            job=self.job,
            status='success',
            started_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=2, minutes=30),
        )
        
        # Create runs after success
        run1 = Run.objects.create(
            job=self.job,
            status='failed',
            started_at=now - timedelta(hours=2),
            ended_at=now - timedelta(hours=1, minutes=45),
        )
        
        run2 = Run.objects.create(
            job=self.job,
            status='pending',
            started_at=now - timedelta(minutes=30),
        )
        
        response = self.client.get('/api/runs/since-last-success/')
        data = response.json()
        
        # Verify the endpoint returns what changed since success
        self.assertEqual(data['last_success_run']['id'], success.id)
        self.assertEqual(data['total_count'], 2)
        self.assertEqual(len(data['runs_since']), 2)
        
        # Verify they're ordered newest first
        ids = [r['id'] for r in data['runs_since']]
        self.assertEqual(ids[0], run2.id)  # Most recent first
        self.assertEqual(ids[1], run1.id)


class ContainerInventorySearchTests(TestCase):
    """Test container inventory functionality"""
    
    def setUp(self):
        self.client = Client()
    
    def test_container_tags_in_inventory(self):
        """Test that container tags are returned in inventory"""
        container = ContainerAllowlist.objects.create(
            container_id='tagged_container',
            container_name='prod-app',
            enabled=True,
            tags=['production', 'critical', 'app-tier']
        )
        
        response = self.client.get('/api/container-inventory/')
        data = response.json()
        
        self.assertEqual(len(data['allowlist']), 1)
        container_data = data['allowlist'][0]
        self.assertEqual(container_data['container_id'], 'tagged_container')
        self.assertEqual(container_data['tags'], ['production', 'critical', 'app-tier'])
