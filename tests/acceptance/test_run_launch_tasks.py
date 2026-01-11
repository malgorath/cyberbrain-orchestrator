from django.test import TestCase
from rest_framework.test import APIClient
from orchestrator.models import Directive, Job as LegacyJob
from core.models import Job as CoreJob


class RunLaunchTasksAcceptanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.directive = Directive.objects.create(
            name='default',
            description='Default directive',
            task_config={}
        )
        for key in ['log_triage', 'gpu_report', 'service_map']:
            CoreJob.objects.get_or_create(task_key=key, defaults={'name': key})

    def test_launch_run_with_explicit_tasks(self):
        payload = {
            'directive': self.directive.id,
            'tasks': ['log_triage', 'gpu_report']
        }
        resp = self.client.post('/api/runs/launch/', payload, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.data['jobs']), 2)
        self.assertEqual(LegacyJob.objects.count(), 2)
