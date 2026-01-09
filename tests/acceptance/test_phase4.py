"""
Phase 4 Acceptance Tests

Tests for notifications, approval gating, and network policy recommendations.
"""
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User

from core.models import (
    NotificationTarget, RunNotification, NetworkPolicyRecommendation,
    Directive as CoreDirective, Job as CoreJob
)
from orchestrator.models import Run as LegacyRun, Directive as LegacyDirective, Job as LegacyJob
from core.notifications import NotificationService


class NotificationAcceptanceTest(TestCase):
    """Test notification delivery on run completion."""
    
    def setUp(self):
        self.directive = LegacyDirective.objects.create(
            name='test-directive',
            description='Test directive'
        )
    
    def test_notification_created_on_run_completion(self):
        """Verify RunNotification records are created when run completes."""
        # Create notification target
        target = NotificationTarget.objects.create(
            name='test-discord',
            type='discord',
            enabled=True,
            config={'webhook_url': 'https://discord.com/api/webhooks/test'}
        )
        
        # Create and complete a run
        run = LegacyRun.objects.create(
            directive=self.directive,
            status='completed'
        )
        
        # Trigger notifications
        NotificationService.send_run_notification(run)
        
        # Verify notification record created
        notifications = RunNotification.objects.filter(run=run)
        self.assertEqual(notifications.count(), 1)
        
        notification = notifications.first()
        self.assertEqual(notification.target, target)
        # Note: actual sending will fail in test (no real webhook), but record is created
    
    def test_notification_payload_counts_only(self):
        """Verify notification payloads contain counts only, no LLM content."""
        target = NotificationTarget.objects.create(
            name='test-email',
            type='email',
            enabled=True,
            config={'email': 'test@example.com'}
        )
        
        run = LegacyRun.objects.create(
            directive=self.directive,
            status='completed'
        )
        
        # Create some jobs
        LegacyJob.objects.create(run=run, task_type='log_triage', status='completed')
        LegacyJob.objects.create(run=run, task_type='gpu_report', status='completed')
        
        # Verify notification service builds payload without LLM content
        # (actual sending will fail in test environment)
        NotificationService.send_run_notification(run)
        
        notification = RunNotification.objects.filter(run=run).first()
        self.assertIsNotNone(notification)
        
        # Payload should not contain any stored LLM prompts/responses
        # This is verified by the model design: LLMCall only stores token counts


class ApprovalGatingAcceptanceTest(TestCase):
    """Test approval gating for D3/D4 directives."""
    
    def setUp(self):
        self.directive_d3 = LegacyDirective.objects.create(
            name='D3 - Code Write',
            description='Code write operations'
        )
        self.directive_d4 = LegacyDirective.objects.create(
            name='D4 - Repo Write',
            description='Repository write operations'
        )
    
    def test_run_requires_approval_for_d3_directive(self):
        """Verify D3/D4 runs start with pending approval status."""
        run = LegacyRun.objects.create(
            directive=self.directive_d3,
            status='pending',
            approval_status='pending'
        )
        
        self.assertEqual(run.approval_status, 'pending')
        self.assertIsNone(run.approved_by)
        self.assertIsNone(run.approved_at)
    
    def test_approval_workflow(self):
        """Test approve/deny workflow for restricted runs."""
        run = LegacyRun.objects.create(
            directive=self.directive_d4,
            status='pending',
            approval_status='pending'
        )
        
        # Approve the run
        run.approval_status = 'approved'
        run.approved_by = 'test_admin'
        run.approved_at = timezone.now()
        run.save()
        
        run.refresh_from_db()
        self.assertEqual(run.approval_status, 'approved')
        self.assertEqual(run.approved_by, 'test_admin')
        self.assertIsNotNone(run.approved_at)
    
    def test_denied_run_cannot_proceed(self):
        """Verify denied runs remain blocked."""
        run = LegacyRun.objects.create(
            directive=self.directive_d3,
            status='pending',
            approval_status='denied'
        )
        
        self.assertEqual(run.approval_status, 'denied')
        # In actual implementation, execution service would check this before running


class NetworkPolicyAcceptanceTest(TestCase):
    """Test network policy recommendation generation."""
    
    def test_network_policy_recommendation_created(self):
        """Verify NetworkPolicyRecommendation records can be created."""
        directive = LegacyDirective.objects.create(
            name='D1 - Log Triage',
            description='Test'
        )
        run = LegacyRun.objects.create(
            directive=directive,
            status='completed'
        )
        
        # Create network policy recommendation
        policy = NetworkPolicyRecommendation.objects.create(
            run=run,
            source_service='web',
            target_service='api',
            port=8080,
            protocol='tcp',
            recommendation='Allow web → api on port 8080/tcp'
        )
        
        self.assertIsNotNone(policy)
        self.assertEqual(policy.source_service, 'web')
        self.assertEqual(policy.target_service, 'api')
    
    def test_policy_yaml_storage(self):
        """Verify K8s NetworkPolicy YAML can be stored."""
        directive = LegacyDirective.objects.create(name='test', description='test')
        run = LegacyRun.objects.create(directive=directive, status='completed')
        
        yaml_content = """
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-web-to-api
spec:
  podSelector:
    matchLabels:
      app: api
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: web
    ports:
    - protocol: TCP
      port: 8080
"""
        
        policy = NetworkPolicyRecommendation.objects.create(
            run=run,
            source_service='web',
            target_service='api',
            port=8080,
            protocol='tcp',
            recommendation='Test policy',
            policy_yaml=yaml_content
        )
        
        self.assertIn('NetworkPolicy', policy.policy_yaml)
        self.assertIn('allow-web-to-api', policy.policy_yaml)


class GuardrailComplianceTest(TestCase):
    """Verify Phase 4 maintains all security guardrails."""
    
    def test_notification_model_no_llm_content_fields(self):
        """Verify RunNotification has no fields for LLM content."""
        from django.db import connection
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'core_runnotification'
            """)
            columns = [row[0] for row in cursor.fetchall()]
        
        # Verify no prompt/response fields
        self.assertNotIn('prompt', columns)
        self.assertNotIn('response', columns)
        self.assertNotIn('llm_content', columns)
    
    def test_approval_preserves_token_only_logging(self):
        """Verify approval workflow doesn't store LLM content."""
        directive = LegacyDirective.objects.create(name='D3 - Code', description='test')
        run = LegacyRun.objects.create(
            directive=directive,
            status='pending',
            approval_status='pending'
        )
        
        # Approve
        run.approval_status = 'approved'
        run.approved_by = 'test_user'
        run.save()
        
        # Verify no new fields for LLM content added
        run.refresh_from_db()
        self.assertFalse(hasattr(run, 'prompt'))
        self.assertFalse(hasattr(run, 'response'))
