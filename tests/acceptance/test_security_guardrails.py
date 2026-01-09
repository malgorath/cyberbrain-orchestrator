"""
Acceptance tests for Security Guardrails (Task 7).

Tests:
- No LLM content storage in database
- Redaction mode works correctly
- Security guardrails are enforced
"""

import logging
from django.test import TestCase, override_settings
from django.conf import settings

from core.models import Directive, Job, Run, LLMCall
from orchestrator.security_guardrails import (
    redact_sensitive_content,
    SecurityGuardrailerViolation,
    get_redacting_logger
)


class NoLLMContentStorageTests(TestCase):
    """Test that LLM content is never stored in the database"""
    
    def setUp(self):
        self.directive = Directive.objects.create(
            directive_type='D1',
            name='Test Directive'
        )
        self.job = Job.objects.create(
            task_key='log_triage',
            name='Log Triage Job',
            default_directive=self.directive
        )
        self.run = Run.objects.create(
            job=self.job,
            status='pending',
        )
    
    def test_llm_call_stores_tokens_only(self):
        """Test that LLMCall only stores token counts"""
        call = LLMCall.objects.create(
            run=self.run,
            endpoint='vllm',
            model_id='llama2',
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        
        # Verify only token counts are stored
        self.assertEqual(call.prompt_tokens, 100)
        self.assertEqual(call.completion_tokens, 50)
        self.assertEqual(call.total_tokens, 150)
        
        # Verify no prompt/response fields exist
        self.assertFalse(hasattr(call, 'prompt'))
        self.assertFalse(hasattr(call, 'response'))
        self.assertFalse(hasattr(call, 'prompt_content'))
        self.assertFalse(hasattr(call, 'response_content'))
    
    def test_run_stores_summary_only(self):
        """Test that Run stores only markdown summary and JSON, not raw content"""
        # Run should store markdown and JSON summaries only
        run = Run.objects.create(
            job=self.job,
            status='success',
            report_markdown='# Summary\nCompleted successfully.',
            report_json={'status': 'success', 'items_processed': 5},
        )
        
        # Verify markdown and JSON are stored as summaries
        self.assertEqual(run.report_markdown, '# Summary\nCompleted successfully.')
        self.assertEqual(run.report_json, {'status': 'success', 'items_processed': 5})
        
        # Verify they're NOT raw LLM responses
        self.assertNotIn('prompt', str(run.report_markdown).lower())
        self.assertNotIn('response', str(run.report_json).lower())
    
    def test_directive_snapshot_stores_no_content(self):
        """Test that directive snapshots store only name and text, not actual prompts"""
        run = Run.objects.create(
            job=self.job,
            status='pending',
            directive_snapshot_name='Test Directive',
            directive_snapshot_text='This is a directive description, not a prompt/response',
        )
        
        # Verify snapshot fields are stored
        self.assertEqual(run.directive_snapshot_name, 'Test Directive')
        self.assertIn('directive description', run.directive_snapshot_text)
        
        # Verify they store configuration/description, not LLM content
        self.assertNotIn('LLM response', run.directive_snapshot_text.lower())


@override_settings(DEBUG_REDACTED_MODE=True)
class RedactionModeTests(TestCase):
    """Test that redaction mode properly hides sensitive content"""
    
    def test_redact_api_keys(self):
        """Test that API keys are redacted"""
        text = 'api_key: sk-1234567890abcdef'
        redacted = redact_sensitive_content(text)
        self.assertNotIn('sk-1234567890abcdef', redacted)
        self.assertIn('[REDACTED_API_KEY]', redacted)
    
    def test_redact_tokens(self):
        """Test that tokens are redacted"""
        text = 'token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'
        redacted = redact_sensitive_content(text)
        self.assertNotIn('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9', redacted)
        self.assertIn('[REDACTED_TOKEN]', redacted)
    
    def test_redact_passwords(self):
        """Test that passwords are redacted"""
        text = 'password: mysecretpassword123'
        redacted = redact_sensitive_content(text)
        self.assertNotIn('mysecretpassword123', redacted)
        self.assertIn('[REDACTED_PASSWORD]', redacted)
    
    def test_redact_ip_addresses(self):
        """Test that IP addresses are redacted"""
        text = 'Connecting to 192.168.1.100'
        redacted = redact_sensitive_content(text)
        self.assertNotIn('192.168.1.100', redacted)
        self.assertIn('[REDACTED_IP]', redacted)
    
    def test_redact_authorization_headers(self):
        """Test that Authorization headers are redacted"""
        text = 'Authorization: Bearer sk-proj-abc123def456'
        redacted = redact_sensitive_content(text)
        self.assertNotIn('sk-proj-abc123def456', redacted)
        self.assertIn('[REDACTED_AUTH]', redacted)
    
    @override_settings(DEBUG_REDACTED_MODE=False)
    def test_no_redaction_when_disabled(self):
        """Test that redaction is disabled when DEBUG_REDACTED_MODE is False"""
        text = 'api_key: sk-1234567890abcdef'
        redacted = redact_sensitive_content(text)
        # When redaction is disabled, content should pass through unchanged
        self.assertIn('sk-1234567890abcdef', redacted)


@override_settings(DEBUG_REDACTED_MODE=True)
class RedactingLoggerTests(TestCase):
    """Test that the redacting logger works correctly"""
    
    def setUp(self):
        self.logger = get_redacting_logger('test_redaction')
        self.handler = logging.StreamHandler()
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)
    
    def test_logger_redacts_messages(self):
        """Test that the logger redacts messages"""
        with self.assertLogs('test_redaction', level='INFO') as cm:
            self.logger.info('api_key: sk-secret123')
        
        # The message should have been redacted
        log_output = ' '.join(cm.output)
        self.assertNotIn('sk-secret123', log_output)
        # Note: Redaction happens in _log(), which is used by the logger internals
    
    def tearDown(self):
        for handler in self.logger.handlers:
            self.logger.removeHandler(handler)


class SecurityGuardrailerViolationTests(TestCase):
    """Test that security guardrails are enforced"""
    
    def setUp(self):
        self.directive = Directive.objects.create(
            directive_type='D1',
            name='Test Directive'
        )
        self.job = Job.objects.create(
            task_key='log_triage',
            name='Test Job',
            default_directive=self.directive
        )
        self.run = Run.objects.create(
            job=self.job,
            status='pending',
        )
    
    def test_llm_call_creation_success(self):
        """Test that creating an LLMCall with only tokens succeeds"""
        # This should succeed - only token counts
        call = LLMCall.objects.create(
            run=self.run,
            endpoint='vllm',
            model_id='llama2',
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        self.assertIsNotNone(call.id)
        self.assertEqual(call.total_tokens, 150)


class GuardrailerMessagesTests(TestCase):
    """Test that guardrail comments are present in code"""
    
    def test_llm_call_has_security_guardrail_comment(self):
        """Test that LLMCall model has security guardrail documentation"""
        from core.models import LLMCall
        # Check that the docstring contains guardrail info
        self.assertIn('GUARDRAIL', LLMCall.__doc__)
        self.assertIn('NEVER', LLMCall.__doc__)
        self.assertIn('prompt', LLMCall.__doc__.lower())
        self.assertIn('response', LLMCall.__doc__.lower())
    
    def test_run_has_security_guardrail_comment(self):
        """Test that Run model has security guardrail documentation"""
        from core.models import Run
        # Check that fields have help_text with guardrail info
        markdown_field = Run._meta.get_field('report_markdown')
        json_field = Run._meta.get_field('report_json')
        
        self.assertIn('GUARDRAIL', markdown_field.help_text)
        self.assertIn('GUARDRAIL', json_field.help_text)


class ProductionSecurityChecksTests(TestCase):
    """Test production security settings"""
    
    def test_debug_redacted_mode_enabled_by_default(self):
        """Test that DEBUG_REDACTED_MODE defaults to True for security"""
        # Should be True by default (from settings.py)
        # This ensures redaction is ON unless explicitly disabled
        from django.conf import settings
        # The default in settings.py is 'True'
        self.assertTrue(settings.DEBUG_REDACTED_MODE)
    
    def test_no_debug_in_production_example(self):
        """Test that DEPLOYMENT.md guides to turn off DEBUG in production"""
        with open('/home/ssanders/Code/cyberbrain-orchestrator/docs/DEPLOYMENT.md', 'r') as f:
            content = f.read()
        
        self.assertIn('DEBUG', content)
        self.assertIn('False', content)
        self.assertIn('production', content.lower())
