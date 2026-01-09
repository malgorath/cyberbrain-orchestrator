"""
Acceptance Tests: Observability Metrics

Tests the built-in metrics system:
- Metrics endpoints return data
- Metrics are recorded on run/job creation
- Metrics are recorded on LLM calls
"""

from django.test import TestCase, Client
from orchestrator.models import Directive, Run, Job
from orchestrator import metrics
import json


class MetricsEndpointTests(TestCase):
    """Test metrics endpoint availability"""
    
    def setUp(self):
        self.client = Client()
        # Reset metrics before each test
        metrics.reset_metrics()
    
    def test_metrics_endpoint_exists(self):
        """/metrics/ must return text format metrics"""
        response = self.client.get('/metrics/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
    
    def test_metrics_json_endpoint_exists(self):
        """/metrics/json/ must return JSON format metrics"""
        response = self.client.get('/metrics/json/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/json', response['Content-Type'])
        
        # Should be valid JSON
        data = response.json()
        self.assertIn('counters', data)
        self.assertIn('gauges', data)
        self.assertIn('histograms', data)


class MetricsRecordingTests(TestCase):
    """Test metrics recording functionality"""
    
    def setUp(self):
        self.client = Client()
        metrics.reset_metrics()
    
    def test_run_creation_recorded(self):
        """Run creation must increment runs_created_total counter"""
        # Record run creation
        metrics.record_run_created(status='pending')
        
        # Check metrics
        response = self.client.get('/metrics/json/')
        data = response.json()
        
        # Should have a counter for runs created
        found = False
        for key, value in data['counters'].items():
            if 'runs_created_total' in key and 'pending' in key:
                found = True
                self.assertEqual(value, 1)
        
        self.assertTrue(found, "runs_created_total counter not found")
    
    def test_job_creation_recorded(self):
        """Job creation must increment jobs_created_total counter"""
        # Record job creations
        metrics.record_job_created(task_key='log_triage')
        metrics.record_job_created(task_key='log_triage')
        metrics.record_job_created(task_key='gpu_report')
        
        # Check metrics
        response = self.client.get('/metrics/json/')
        data = response.json()
        
        # Should have counters for jobs created
        log_triage_count = 0
        gpu_report_count = 0
        
        for key, value in data['counters'].items():
            if 'jobs_created_total' in key:
                if 'log_triage' in key:
                    log_triage_count = value
                elif 'gpu_report' in key:
                    gpu_report_count = value
        
        self.assertEqual(log_triage_count, 2)
        self.assertEqual(gpu_report_count, 1)
    
    def test_llm_tokens_recorded(self):
        """LLM token usage must increment llm_tokens_total counter"""
        # Record LLM tokens
        metrics.record_llm_tokens(
            model_id='mistral-7b',
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150
        )
        
        # Check metrics
        response = self.client.get('/metrics/json/')
        data = response.json()
        
        # Should have counters for token types
        found_prompt = False
        found_completion = False
        found_total = False
        
        for key, value in data['counters'].items():
            if 'llm_tokens_total' in key and 'mistral-7b' in key:
                if 'prompt' in key:
                    found_prompt = True
                    self.assertEqual(value, 100)
                elif 'completion' in key:
                    found_completion = True
                    self.assertEqual(value, 50)
                elif 'total' in key:
                    found_total = True
                    self.assertEqual(value, 150)
        
        self.assertTrue(found_prompt, "prompt tokens not recorded")
        self.assertTrue(found_completion, "completion tokens not recorded")
        self.assertTrue(found_total, "total tokens not recorded")
    
    def test_job_duration_histogram(self):
        """Job duration must be recorded in histogram"""
        # Record job durations
        metrics.record_job_duration('log_triage', 'completed', 5.5)
        metrics.record_job_duration('log_triage', 'completed', 7.2)
        metrics.record_job_duration('log_triage', 'completed', 6.1)
        
        # Check metrics
        response = self.client.get('/metrics/json/')
        data = response.json()
        
        # Should have histogram stats
        found = False
        for key, stats in data['histograms'].items():
            if 'jobs_duration_seconds' in key and 'log_triage' in key:
                found = True
                self.assertEqual(stats['count'], 3)
                self.assertAlmostEqual(stats['sum'], 18.8, places=1)
                self.assertAlmostEqual(stats['avg'], 6.27, places=1)
                self.assertAlmostEqual(stats['min'], 5.5, places=1)
                self.assertAlmostEqual(stats['max'], 7.2, places=1)
        
        self.assertTrue(found, "job duration histogram not found")


class MetricsIntegrationTests(TestCase):
    """Test metrics integration with API"""
    
    def setUp(self):
        self.client = Client()
        metrics.reset_metrics()
        self.directive = Directive.objects.create(
            name='test',
            description='Test directive'
        )
    
    def test_launch_endpoint_records_metrics(self):
        """Launch endpoint must record run and job creation metrics"""
        # Launch a run
        response = self.client.post('/api/runs/launch/', {
            'tasks': ['log_triage', 'gpu_report']
        }, content_type='application/json')
        
        self.assertEqual(response.status_code, 201)
        
        # Check metrics
        metrics_response = self.client.get('/metrics/json/')
        data = metrics_response.json()
        
        # Should have recorded 1 run and 2 jobs
        run_created = False
        log_triage_created = False
        gpu_report_created = False
        
        for key, value in data['counters'].items():
            if 'runs_created_total' in key:
                run_created = (value >= 1)
            if 'jobs_created_total' in key:
                if 'log_triage' in key:
                    log_triage_created = (value >= 1)
                elif 'gpu_report' in key:
                    gpu_report_created = (value >= 1)
        
        self.assertTrue(run_created, "Run creation not recorded")
        self.assertTrue(log_triage_created, "log_triage job creation not recorded")
        self.assertTrue(gpu_report_created, "gpu_report job creation not recorded")


if __name__ == '__main__':
    import unittest
    unittest.main()
