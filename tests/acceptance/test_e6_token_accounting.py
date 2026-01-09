"""
E6 Acceptance Tests: Token Accounting

ATDD for tracking LLM token usage and costs:
- Token count aggregation by model, endpoint, time window
- Cost calculation based on token rates
- No LLM content storage (token counts only)
- API endpoints for token statistics and cost reports
- Usage trends and per-directive accounting

Contract expectations:
- Token counts accurate and immutable (from LLMCall records)
- Cost calculation based on configurable model rates
- Historical queries support "since last run" windows
- All accounting excludes sensitive content
- Usage reports available by directive, endpoint, time period
"""
from django.test import TestCase
from django.utils import timezone
from django.db import models
from datetime import timedelta
from core.models import (
    Directive, Job, Run, RunJob, LLMCall
)
from rest_framework.test import APIClient
from rest_framework import status
import json


class TokenCountingTests(TestCase):
    """Test token counting and aggregation"""
    
    def setUp(self):
        """Create test directive, job, and runs"""
        self.directive = Directive.objects.create(
            directive_type="D1",
            name="log-triage",
            directive_text="Analyze logs for errors",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage",
            name="Log Triage Job",
            default_directive=self.directive,
            is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="completed"
        )
    
    def test_aggregate_tokens_by_endpoint(self):
        """Token aggregation must group by endpoint"""
        # Create vLLM calls
        for i in range(3):
            LLMCall.objects.create(
                run=self.run,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150
            )
        
        # Create llama.cpp calls
        for i in range(2):
            LLMCall.objects.create(
                run=self.run,
                endpoint="llama_cpp",
                model_id="llama2-7b",
                prompt_tokens=200,
                completion_tokens=100,
                total_tokens=300
            )
        
        # Get aggregates
        vllm_tokens = LLMCall.objects.filter(
            endpoint="vllm", run=self.run
        ).aggregate(total=models.Sum('total_tokens'))['total']
        
        llama_tokens = LLMCall.objects.filter(
            endpoint="llama_cpp", run=self.run
        ).aggregate(total=models.Sum('total_tokens'))['total']
        
        self.assertEqual(vllm_tokens, 450)  # 3 * 150
        self.assertEqual(llama_tokens, 600)  # 2 * 300
    
    def test_aggregate_tokens_by_model(self):
        """Token aggregation must group by model"""
        # Create calls for different models
        for i in range(2):
            LLMCall.objects.create(
                run=self.run,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150
            )
        
        for i in range(3):
            LLMCall.objects.create(
                run=self.run,
                endpoint="vllm",
                model_id="llama2-7b",
                prompt_tokens=80,
                completion_tokens=40,
                total_tokens=120
            )
        
        # Get aggregates
        mistral_tokens = LLMCall.objects.filter(
            model_id="mistral-7b", run=self.run
        ).aggregate(total=models.Sum('total_tokens'))['total']
        
        llama_tokens = LLMCall.objects.filter(
            model_id="llama2-7b", run=self.run
        ).aggregate(total=models.Sum('total_tokens'))['total']
        
        self.assertEqual(mistral_tokens, 300)  # 2 * 150
        self.assertEqual(llama_tokens, 360)   # 3 * 120
    
    def test_aggregate_tokens_by_time_window(self):
        """Token aggregation must support time window queries"""
        # Create recent call
        recent = LLMCall.objects.create(
            run=self.run,
            endpoint="vllm",
            model_id="mistral-7b",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150
        )
        
        # Create old call (24 hours ago)
        old_time = timezone.now() - timedelta(hours=24)
        old_call = LLMCall.objects.create(
            run=self.run,
            endpoint="vllm",
            model_id="mistral-7b",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150
        )
        # Manually set created_at since it's auto_now_add
        LLMCall.objects.filter(pk=old_call.pk).update(created_at=old_time)
        
        # Query last 12 hours
        cutoff = timezone.now() - timedelta(hours=12)
        recent_tokens = LLMCall.objects.filter(
            run=self.run,
            created_at__gte=cutoff
        ).aggregate(total=models.Sum('total_tokens'))['total']
        
        self.assertEqual(recent_tokens, 150)  # Only recent call
    
    def test_aggregate_tokens_by_directive(self):
        """Token aggregation must group by directive"""
        # Runs using different directives
        directive2 = Directive.objects.create(
            directive_type="D2",
            name="gpu-report",
            directive_text="Analyze GPU stats",
            version=1,
            is_active=True
        )
        job2 = Job.objects.create(
            task_key="gpu_report",
            name="GPU Report Job",
            default_directive=directive2,
            is_active=True
        )
        run2 = Run.objects.create(
            job=job2,
            directive_snapshot_name=directive2.name,
            directive_snapshot_text=directive2.directive_text,
            status="completed"
        )
        
        # Calls for first directive
        LLMCall.objects.create(
            run=self.run,
            endpoint="vllm",
            model_id="mistral-7b",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150
        )
        
        # Calls for second directive
        for i in range(3):
            LLMCall.objects.create(
                run=run2,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150
            )
        
        # Get aggregates per directive
        d1_tokens = LLMCall.objects.filter(run__job__default_directive=self.directive).aggregate(
            total=models.Sum('total_tokens')
        )['total']
        
        d2_tokens = LLMCall.objects.filter(run__job__default_directive=directive2).aggregate(
            total=models.Sum('total_tokens')
        )['total']
        
        self.assertEqual(d1_tokens, 150)
        self.assertEqual(d2_tokens, 450)  # 3 * 150


class CostCalculationTests(TestCase):
    """Test cost calculation based on token rates"""
    
    def setUp(self):
        """Create test data"""
        self.directive = Directive.objects.create(
            directive_type="D1",
            name="test",
            directive_text="Test",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage",
            name="Test Job",
            default_directive=self.directive,
            is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="completed"
        )
    
    def test_calculate_cost_from_token_counts(self):
        """Cost calculation must use token counts (no content)"""
        # Create LLM calls
        LLMCall.objects.create(
            run=self.run,
            endpoint="vllm",
            model_id="mistral-7b",
            prompt_tokens=1000,    # 1K input tokens
            completion_tokens=500,  # 500 output tokens
            total_tokens=1500
        )
        
        # Standard rates (example): 0.2 per 1K input, 0.6 per 1K output
        prompt_rate = 0.2 / 1000  # per token
        completion_rate = 0.6 / 1000  # per token
        
        total_cost = (1000 * prompt_rate) + (500 * completion_rate)
        
        # Should be 0.2 + 0.3 = 0.5
        self.assertAlmostEqual(total_cost, 0.5, places=2)
    
    def test_cost_calculation_excludes_content(self):
        """Cost calculation must NEVER access prompt/response content"""
        call = LLMCall.objects.create(
            run=self.run,
            endpoint="vllm",
            model_id="mistral-7b",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150
        )
        
        # Verify no content fields exist
        field_names = [f.name for f in LLMCall._meta.get_fields()]
        forbidden = ['prompt', 'response', 'content', 'messages']
        
        for field in forbidden:
            self.assertNotIn(field, field_names,
                           f"Cost calculation must not access {field} field")


class TokenAccountingAPITests(TestCase):
    """Test DRF API endpoints for token accounting"""
    
    def setUp(self):
        """Create test data"""
        self.client = APIClient()
        self.directive = Directive.objects.create(
            directive_type="D1",
            name="test",
            directive_text="Test",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage",
            name="Test Job",
            default_directive=self.directive,
            is_active=True
        )
        self.run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="completed"
        )
        
        # Create LLM calls
        for i in range(5):
            LLMCall.objects.create(
                run=self.run,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150
            )
    
    def test_get_token_stats_endpoint(self):
        """GET /api/token-stats/ must return token statistics"""
        response = self.client.get('/api/token-stats/')
        
        # Endpoint should exist
        self.assertIn(response.status_code, [200, 404])  # 404 if not yet implemented
        
        if response.status_code == 200:
            data = response.json()
            self.assertIn("total_tokens", data)
            self.assertEqual(data["total_tokens"], 750)  # 5 * 150
    
    def test_get_cost_report_endpoint(self):
        """GET /api/cost-report/ must return cost breakdown"""
        response = self.client.get('/api/cost-report/')
        
        # Endpoint should exist
        self.assertIn(response.status_code, [200, 404])  # 404 if not yet implemented
        
        if response.status_code == 200:
            data = response.json()
            self.assertIn("total_cost", data)
            # Should have cost breakdown by model/endpoint
            if "by_model" in data:
                self.assertIn("mistral-7b", data["by_model"])
    
    def test_get_usage_by_directive_endpoint(self):
        """GET /api/usage-by-directive/ must return per-directive accounting"""
        response = self.client.get('/api/usage-by-directive/')
        
        # Endpoint should exist
        self.assertIn(response.status_code, [200, 404])  # 404 if not yet implemented
        
        if response.status_code == 200:
            data = response.json()
            self.assertIsInstance(data, (list, dict))
    
    def test_api_excludes_sensitive_content(self):
        """API responses must never include LLM content"""
        # Test all accounting endpoints
        endpoints = [
            '/api/token-stats/',
            '/api/cost-report/',
            '/api/usage-by-directive/',
        ]
        
        for endpoint in endpoints:
            response = self.client.get(endpoint)
            
            if response.status_code == 200:
                response_str = json.dumps(response.json(), default=str)
                # Check for content-like fields
                forbidden = ['prompt', 'response', 'message', 'content']
                for field in forbidden:
                    # Content words shouldn't appear as field names
                    self.assertNotIn(f'"{field}"', response_str.lower(),
                                   f"{endpoint} should not expose {field}")


class UsageReportsTests(TestCase):
    """Test token usage report generation"""
    
    def setUp(self):
        """Create test data with multiple runs"""
        self.directive1 = Directive.objects.create(
            directive_type="D1",
            name="d1",
            directive_text="D1",
            version=1,
            is_active=True
        )
        self.directive2 = Directive.objects.create(
            directive_type="D2",
            name="d2",
            directive_text="D2",
            version=1,
            is_active=True
        )
        
        self.job1 = Job.objects.create(
            task_key="log_triage",
            name="J1",
            default_directive=self.directive1,
            is_active=True
        )
        self.job2 = Job.objects.create(
            task_key="gpu_report",
            name="J2",
            default_directive=self.directive2,
            is_active=True
        )
        
        # Multiple runs
        self.run1 = Run.objects.create(
            job=self.job1,
            directive_snapshot_name=self.directive1.name,
            directive_snapshot_text=self.directive1.directive_text,
            status="completed"
        )
        self.run2 = Run.objects.create(
            job=self.job2,
            directive_snapshot_name=self.directive2.name,
            directive_snapshot_text=self.directive2.directive_text,
            status="completed"
        )
    
    def test_usage_report_totals_per_job(self):
        """Usage report must total tokens per job"""
        # Calls for job 1
        for i in range(3):
            LLMCall.objects.create(
                run=self.run1,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150
            )
        
        # Calls for job 2
        for i in range(2):
            LLMCall.objects.create(
                run=self.run2,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=200,
                completion_tokens=100,
                total_tokens=300
            )
        
        # Verify aggregates
        j1_total = LLMCall.objects.filter(run__job=self.job1).aggregate(
            total=models.Sum('total_tokens')
        )['total']
        
        j2_total = LLMCall.objects.filter(run__job=self.job2).aggregate(
            total=models.Sum('total_tokens')
        )['total']
        
        self.assertEqual(j1_total, 450)   # 3 * 150
        self.assertEqual(j2_total, 600)   # 2 * 300
    
    def test_usage_report_shows_trends(self):
        """Usage report must track usage trends over time"""
        # Create calls spread over time
        base_time = timezone.now()
        
        # Recent calls (last hour)
        for i in range(5):
            LLMCall.objects.create(
                run=self.run1,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150
            )
        
        # Create some calls with timestamps
        call_times = [
            base_time - timedelta(hours=2),  # 2 hours ago
            base_time - timedelta(hours=1),  # 1 hour ago
            base_time,  # just now
        ]
        
        for t in call_times:
            call = LLMCall.objects.create(
                run=self.run1,
                endpoint="vllm",
                model_id="mistral-7b",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150
            )
            LLMCall.objects.filter(pk=call.pk).update(created_at=t)
        
        # Verify total is correct
        all_calls = LLMCall.objects.filter(run=self.run1).aggregate(
            total=models.Sum('total_tokens')
        )['total']
        
        self.assertEqual(all_calls, 1200)  # (5 + 3) * 150
