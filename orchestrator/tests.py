from django.test import TestCase
from django.utils import timezone
from .models import Directive, Run, Job, LLMCall, ContainerAllowlist


class DirectiveModelTest(TestCase):
    """Test cases for Directive model"""

    def test_create_directive(self):
        """Test creating a directive"""
        directive = Directive.objects.create(
            name='test_directive',
            description='Test description',
            task_config={'key': 'value'}
        )
        self.assertEqual(directive.name, 'test_directive')
        self.assertEqual(directive.description, 'Test description')
        self.assertEqual(directive.task_config, {'key': 'value'})

    def test_directive_str(self):
        """Test directive string representation"""
        directive = Directive.objects.create(name='test')
        self.assertEqual(str(directive), 'test')


class RunModelTest(TestCase):
    """Test cases for Run model"""

    def setUp(self):
        self.directive = Directive.objects.create(name='test_directive')

    def test_create_run(self):
        """Test creating a run"""
        run = Run.objects.create(
            directive=self.directive,
            status='pending'
        )
        self.assertEqual(run.directive, self.directive)
        self.assertEqual(run.status, 'pending')
        self.assertIsNotNone(run.started_at)

    def test_run_str(self):
        """Test run string representation"""
        run = Run.objects.create(directive=self.directive)
        self.assertIn('Run', str(run))
        self.assertIn('test_directive', str(run))


class JobModelTest(TestCase):
    """Test cases for Job model"""

    def setUp(self):
        self.directive = Directive.objects.create(name='test_directive')
        self.run = Run.objects.create(directive=self.directive)

    def test_create_job(self):
        """Test creating a job"""
        job = Job.objects.create(
            run=self.run,
            task_type='log_triage',
            status='pending'
        )
        self.assertEqual(job.run, self.run)
        self.assertEqual(job.task_type, 'log_triage')
        self.assertEqual(job.status, 'pending')

    def test_job_task_choices(self):
        """Test that all task types are valid"""
        task_types = ['log_triage', 'gpu_report', 'service_map']
        for task_type in task_types:
            job = Job.objects.create(
                run=self.run,
                task_type=task_type
            )
            self.assertEqual(job.task_type, task_type)


class LLMCallModelTest(TestCase):
    """Test cases for LLMCall model"""

    def setUp(self):
        self.directive = Directive.objects.create(name='test_directive')
        self.run = Run.objects.create(directive=self.directive)
        self.job = Job.objects.create(run=self.run, task_type='log_triage')

    def test_create_llm_call(self):
        """Test creating an LLM call"""
        llm_call = LLMCall.objects.create(
            job=self.job,
            model_name='gpt-4',
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300
        )
        self.assertEqual(llm_call.job, self.job)
        self.assertEqual(llm_call.model_name, 'gpt-4')
        self.assertEqual(llm_call.prompt_tokens, 100)
        self.assertEqual(llm_call.completion_tokens, 200)
        self.assertEqual(llm_call.total_tokens, 300)


class ContainerAllowlistModelTest(TestCase):
    """Test cases for ContainerAllowlist model"""

    def test_create_container(self):
        """Test creating a container allowlist entry"""
        container = ContainerAllowlist.objects.create(
            container_id='abc123',
            name='test_container',
            description='Test container',
            is_active=True
        )
        self.assertEqual(container.container_id, 'abc123')
        self.assertEqual(container.name, 'test_container')
        self.assertTrue(container.is_active)

    def test_container_str(self):
        """Test container string representation"""
        container = ContainerAllowlist.objects.create(
            container_id='abc123',
            name='test_container'
        )
        self.assertIn('test_container', str(container))
        self.assertIn('abc123', str(container))

