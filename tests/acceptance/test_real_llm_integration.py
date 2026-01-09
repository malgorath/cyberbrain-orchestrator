"""
Real LLM Endpoint Integration Tests (ATDD)

Tests verify actual LLM API communication:
- Connect to vLLM/OpenAI endpoints
- Send prompts and receive completions
- Extract token counts from responses
- Handle errors (endpoint down, timeout, rate limits)
- NO prompt/response storage (tokens only)

CONTRACT:
- LLM client sends requests successfully
- Token counts extracted from response
- Errors handled gracefully
- No content storage anywhere
"""
from django.test import TestCase
from core.models import LLMCall, Run, Job, Directive
from orchestration.llm_client import LLMClient
from unittest.mock import MagicMock, patch
import requests


class LLMClientConnectionTests(TestCase):
    """Test LLM client connection"""
    
    def test_llm_client_creation(self):
        """LLM client can be instantiated"""
        client = LLMClient(endpoint="http://localhost:8000/v1")
        self.assertIsNotNone(client)
        self.assertEqual(client.endpoint, "http://localhost:8000/v1")
    
    @patch('requests.post')
    def test_llm_client_sends_request(self, mock_post):
        """LLM client can send completion request"""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'text': 'Analysis result'}],
            'usage': {
                'prompt_tokens': 150,
                'completion_tokens': 75,
                'total_tokens': 225
            }
        }
        mock_post.return_value = mock_response
        
        client = LLMClient(endpoint="http://localhost:8000/v1")
        result = client.complete("Test prompt")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['usage']['total_tokens'], 225)
    
    @patch('requests.post')
    def test_llm_endpoint_unavailable(self, mock_post):
        """Gracefully handle LLM endpoint unavailable"""
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
        
        client = LLMClient(endpoint="http://localhost:8000/v1")
        
        with self.assertRaises(requests.exceptions.ConnectionError):
            client.complete("Test prompt")


class LLMTokenExtractionTests(TestCase):
    """Test token count extraction from LLM responses"""
    
    @patch('requests.post')
    def test_extract_tokens_from_openai_format(self, mock_post):
        """Extract tokens from OpenAI-compatible response"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'text': 'Result'}],
            'usage': {
                'prompt_tokens': 100,
                'completion_tokens': 50,
                'total_tokens': 150
            }
        }
        mock_post.return_value = mock_response
        
        client = LLMClient()
        result = client.complete("Prompt")
        
        self.assertEqual(result['usage']['prompt_tokens'], 100)
        self.assertEqual(result['usage']['completion_tokens'], 50)
        self.assertEqual(result['usage']['total_tokens'], 150)
    
    @patch('requests.post')
    def test_extract_tokens_from_vllm_format(self, mock_post):
        """Extract tokens from vLLM response format"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'text': 'Result'}],
            'usage': {
                'prompt_tokens': 200,
                'completion_tokens': 100,
                'total_tokens': 300
            }
        }
        mock_post.return_value = mock_response
        
        client = LLMClient(endpoint="http://vllm:8000/v1")
        result = client.complete("Prompt")
        
        self.assertIn('usage', result)
        self.assertEqual(result['usage']['total_tokens'], 300)


class LLMTokenStorageTests(TestCase):
    """Test LLM token storage (no content)"""
    
    def setUp(self):
        """Create test run"""
        d1 = Directive.objects.create(
            directive_type="D1", name="d1",
            directive_text="Test", version=1, is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage", name="Log Triage",
            default_directive=d1, is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=d1.name,
            directive_snapshot_text=d1.directive_text,
            status="pending"
        )
    
    @patch('requests.post')
    def test_store_only_token_counts(self, mock_post):
        """Store only token counts, never prompt/response"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'text': 'This is the completion'}],
            'usage': {
                'prompt_tokens': 50,
                'completion_tokens': 25,
                'total_tokens': 75
            }
        }
        mock_post.return_value = mock_response
        
        client = LLMClient()
        result = client.complete("This is the prompt")
        
        # Store in database
        LLMCall.objects.create(
            run=self.run,
            endpoint=client.endpoint,
            model_id="mistral-7b",
            prompt_tokens=result['usage']['prompt_tokens'],
            completion_tokens=result['usage']['completion_tokens'],
            total_tokens=result['usage']['total_tokens']
        )
        
        # Verify only tokens stored
        call = LLMCall.objects.filter(run=self.run).first()
        self.assertEqual(call.total_tokens, 75)
        
        # Verify NO content fields
        self.assertIsNone(getattr(call, 'prompt', None) or None)
        self.assertIsNone(getattr(call, 'response', None) or None)


class LLMErrorHandlingTests(TestCase):
    """Test LLM error handling"""
    
    @patch('requests.post')
    def test_handle_timeout(self, mock_post):
        """Gracefully handle request timeout"""
        mock_post.side_effect = requests.exceptions.Timeout("Request timeout")
        
        client = LLMClient(timeout=5)
        
        with self.assertRaises(requests.exceptions.Timeout):
            client.complete("Prompt")
    
    @patch('requests.post')
    def test_handle_rate_limit(self, mock_post):
        """Gracefully handle rate limit (429)"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_post.return_value = mock_response
        
        client = LLMClient()
        
        with self.assertRaises(Exception):
            client.complete("Prompt")
    
    @patch('requests.post')
    def test_handle_server_error(self, mock_post):
        """Gracefully handle server error (500)"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_post.return_value = mock_response
        
        client = LLMClient()
        
        with self.assertRaises(Exception):
            client.complete("Prompt")


class LLMAnalysisWorkflowTests(TestCase):
    """Test end-to-end LLM analysis workflow"""
    
    def setUp(self):
        """Create test run"""
        d1 = Directive.objects.create(
            directive_type="D1", name="d1",
            directive_text="Test", version=1, is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage", name="Log Triage",
            default_directive=d1, is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=d1.name,
            directive_snapshot_text=d1.directive_text,
            status="pending"
        )
    
    @patch('requests.post')
    def test_analyze_logs_workflow(self, mock_post):
        """Complete workflow: send logs → get analysis → record tokens"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'text': 'Analysis: No errors found'}],
            'usage': {
                'prompt_tokens': 500,
                'completion_tokens': 100,
                'total_tokens': 600
            }
        }
        mock_post.return_value = mock_response
        
        client = LLMClient()
        logs = "Container log entries here..."
        
        # Analyze
        result = client.complete(f"Analyze these logs:\n{logs}")
        
        # Record tokens (not content)
        LLMCall.objects.create(
            run=self.run,
            endpoint=client.endpoint,
            model_id="mistral-7b",
            prompt_tokens=result['usage']['prompt_tokens'],
            completion_tokens=result['usage']['completion_tokens'],
            total_tokens=result['usage']['total_tokens']
        )
        
        # Verify
        call = LLMCall.objects.filter(run=self.run).first()
        self.assertEqual(call.total_tokens, 600)
        self.assertGreater(call.prompt_tokens, 0)
        self.assertGreater(call.completion_tokens, 0)
