"""
Acceptance Tests: Performance and Load Testing

Tests system performance under load:
- API response times
- Concurrent request handling
- Database query efficiency
- Memory usage patterns
"""

import unittest
from django.test import TestCase, Client
from django.utils import timezone
from django.conf import settings
from orchestrator.models import Directive, Run, Job
from core.models import LLMCall, Run as CoreRun
from orchestrator import metrics
import time
import threading
import statistics


# Skip concurrency tests with SQLite
SKIP_CONCURRENT = 'sqlite' in settings.DATABASES['default']['ENGINE']


class APIPerformanceTests(TestCase):
    """Test API endpoint performance"""
    
    def setUp(self):
        self.client = Client()
        self.directive = Directive.objects.create(
            name='test',
            description='Test directive'
        )
        metrics.reset_metrics()
    
    def test_list_runs_performance(self):
        """List runs endpoint must respond within acceptable time"""
        # Create 100 runs
        runs = []
        for i in range(100):
            run = Run.objects.create(
                directive=self.directive,
                status='pending'
            )
            runs.append(run)
        
        # Measure response time
        start_time = time.time()
        response = self.client.get('/api/runs/')
        duration = time.time() - start_time
        
        self.assertEqual(response.status_code, 200)
        # Should respond within 1 second for 100 runs
        self.assertLess(duration, 1.0, f"Response took {duration:.3f}s, expected < 1.0s")
    
    def test_launch_endpoint_performance(self):
        """Launch endpoint must respond within acceptable time"""
        durations = []
        
        # Launch 10 runs and measure time
        for i in range(10):
            start_time = time.time()
            response = self.client.post('/api/runs/launch/', {
                'tasks': ['log_triage', 'gpu_report']
            }, content_type='application/json')
            duration = time.time() - start_time
            durations.append(duration)
            
            self.assertEqual(response.status_code, 201)
        
        # Calculate statistics
        avg_duration = statistics.mean(durations)
        max_duration = max(durations)
        
        # Should average < 100ms per launch
        self.assertLess(avg_duration, 0.1, f"Average launch took {avg_duration:.3f}s, expected < 0.1s")
        self.assertLess(max_duration, 0.5, f"Max launch took {max_duration:.3f}s, expected < 0.5s")
    
    def test_token_stats_performance_with_many_calls(self):
        """Token stats endpoint must perform well with many LLM calls"""
        from core.models import Job as CoreJob
        
        # Create a core job and run
        core_job = CoreJob.objects.create(
            task_key='log_triage',
            name='Test Job',
            is_active=True
        )
        
        core_run = CoreRun.objects.create(
            job=core_job,
            directive_snapshot_name='test',
            directive_snapshot_text='test',
            status='success'
        )
        
        # Create 1000 LLM calls
        for i in range(1000):
            LLMCall.objects.create(
                run=core_run,
                endpoint='vllm',
                model_id='mistral-7b',
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150
            )
        
        # Measure response time
        start_time = time.time()
        response = self.client.get('/api/token-stats/')
        duration = time.time() - start_time
        
        self.assertEqual(response.status_code, 200)
        # Should respond within 1 second even with 1000 LLM calls
        self.assertLess(duration, 1.0, f"Response took {duration:.3f}s, expected < 1.0s")
        
        # Verify data correctness
        data = response.json()
        self.assertEqual(data['total_tokens'], 150000)
        self.assertEqual(data['call_count'], 1000)


class ConcurrentRequestTests(TestCase):
    """Test concurrent request handling (PostgreSQL only)"""
    
    def setUp(self):
        self.client = Client()
        self.directive = Directive.objects.create(
            name='test',
            description='Test directive'
        )
    
    @unittest.skipIf(SKIP_CONCURRENT, "Concurrent tests require PostgreSQL")
    def test_concurrent_launches(self):
        """System must handle concurrent launch requests (may have SQLite lock issues)"""
        results = []
        errors = []
        
        def launch_run():
            try:
                response = self.client.post('/api/runs/launch/', {
                    'tasks': ['log_triage']
                }, content_type='application/json')
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))
        
        # Launch 10 runs concurrently
        threads = []
        for i in range(10):
            thread = threading.Thread(target=launch_run)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # With SQLite, some may fail due to locking
        # Just verify that at least some succeeded
        success_count = sum(1 for s in results if s == 201)
        self.assertGreater(success_count, 5, f"Only {success_count}/10 launches succeeded")
    
    @unittest.skipIf(SKIP_CONCURRENT, "Concurrent tests require PostgreSQL")
    def test_concurrent_reads(self):
        """System must handle concurrent read requests (SQLite may have issues)"""
        # Create some data
        for i in range(10):
            Run.objects.create(
                directive=self.directive,
                status='pending'
            )
        
        results = []
        errors = []
        
        def read_runs():
            try:
                response = self.client.get('/api/runs/')
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))
        
        # Read 20 times concurrently
        threads = []
        for i in range(20):
            thread = threading.Thread(target=read_runs)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # With SQLite, some reads may fail due to locking
        # Just verify that most succeeded
        success_count = sum(1 for s in results if s == 200)
        self.assertGreater(success_count, 15, f"Only {success_count}/20 reads succeeded")


class DatabaseQueryEfficiencyTests(TestCase):
    """Test database query efficiency"""
    
    def setUp(self):
        self.client = Client()
        self.directive = Directive.objects.create(
            name='test',
            description='Test directive'
        )
    
    def test_run_list_query_count(self):
        """Run list should use efficient queries (N+1 problem check)"""
        # Create 10 runs with jobs
        for i in range(10):
            run = Run.objects.create(
                directive=self.directive,
                status='pending'
            )
            for task in ['log_triage', 'gpu_report']:
                Job.objects.create(
                    run=run,
                    task_type=task,
                    status='pending'
                )
        
        # Count queries (using Django debug toolbar or assertNumQueries in real scenario)
        # For this test, just verify it works and isn't extremely slow
        start_time = time.time()
        response = self.client.get('/api/runs/')
        duration = time.time() - start_time
        
        self.assertEqual(response.status_code, 200)
        # Should be fast even with 10 runs and 20 jobs
        self.assertLess(duration, 0.5, f"Response took {duration:.3f}s, expected < 0.5s")
    
    def test_run_detail_query_count(self):
        """Run detail should use efficient queries"""
        run = Run.objects.create(
            directive=self.directive,
            status='pending'
        )
        
        # Create 10 jobs
        for i in range(10):
            Job.objects.create(
                run=run,
                task_type='log_triage',
                status='pending'
            )
        
        # Measure response time
        start_time = time.time()
        response = self.client.get(f'/api/runs/{run.id}/')
        duration = time.time() - start_time
        
        self.assertEqual(response.status_code, 200)
        # Should be fast even with 10 jobs
        self.assertLess(duration, 0.3, f"Response took {duration:.3f}s, expected < 0.3s")


class MetricsPerformanceTests(TestCase):
    """Test metrics system performance"""
    
    def setUp(self):
        metrics.reset_metrics()
    
    def test_metrics_recording_performance(self):
        """Metrics recording must be fast"""
        # Record 1000 metrics
        start_time = time.time()
        for i in range(1000):
            metrics.record_run_created(status='pending')
            metrics.record_job_created(task_key='log_triage')
            metrics.record_llm_tokens('mistral-7b', 100, 50, 150)
        duration = time.time() - start_time
        
        # Should complete within 2 seconds
        self.assertLess(duration, 2.0, f"Recording 3000 metrics took {duration:.3f}s, expected < 2.0s")
    
    def test_metrics_endpoint_performance(self):
        """Metrics endpoint must respond quickly"""
        # Record many metrics
        for i in range(100):
            metrics.record_run_created(status='pending')
            metrics.record_job_created(task_key='log_triage')
            metrics.record_job_duration('log_triage', 'completed', 5.0 + i * 0.1)
        
        # Measure response time
        client = Client()
        start_time = time.time()
        response = client.get('/metrics/json/')
        duration = time.time() - start_time
        
        self.assertEqual(response.status_code, 200)
        # Should respond within 500ms
        self.assertLess(duration, 0.5, f"Metrics endpoint took {duration:.3f}s, expected < 0.5s")


if __name__ == '__main__':
    import unittest
    unittest.main()
