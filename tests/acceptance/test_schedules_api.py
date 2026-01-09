from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.utils import timezone
from core.models import Directive, Job as CoreJob


class ScheduleApiAcceptanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Ensure core Job templates exist for tasks
        for key, name in [
            ('log_triage', 'Log Triage'),
            ('gpu_report', 'GPU Report'),
            ('service_map', 'Service Map'),
        ]:
            CoreJob.objects.get_or_create(task_key=key, defaults={'name': name})

        # Create a default directive in core to reference if needed
        self.directive = Directive.objects.create(
            directive_type='D1',
            name='D1 Default',
            description='Default D1 directive',
            is_builtin=True,
        )

    def test_create_interval_schedule_and_run_now(self):
        # Create schedule via API
        payload = {
            'name': 'Every 5 minutes triage',
            'job_key': 'log_triage',
            'enabled': True,
            'schedule_type': 'interval',
            'interval_minutes': 5,
            'timezone': 'UTC',
        }
        resp = self.client.post('/api/schedules/', payload, format='json')
        self.assertEqual(resp.status_code, 201)
        schedule_id = resp.data['id']
        self.assertTrue(resp.data['next_run_at'])

        # Run now action
        run_now = self.client.post(f'/api/schedules/{schedule_id}/run-now/')
        self.assertEqual(run_now.status_code, 201)
        self.assertIn('run_id', run_now.data)

        # Verify schedule timestamps updated
        get_resp = self.client.get(f'/api/schedules/{schedule_id}/')
        self.assertEqual(get_resp.status_code, 200)
        self.assertIsNotNone(get_resp.data['last_run_at'])
        self.assertIsNotNone(get_resp.data['next_run_at'])

    def test_enable_disable_schedule(self):
        payload = {
            'name': 'GPU report hourly',
            'job_key': 'gpu_report',
            'enabled': False,
            'schedule_type': 'interval',
            'interval_minutes': 60,
            'timezone': 'UTC',
        }
        resp = self.client.post('/api/schedules/', payload, format='json')
        self.assertEqual(resp.status_code, 201)
        schedule_id = resp.data['id']
        self.assertFalse(resp.data['enabled'])

        # Enable
        en = self.client.post(f'/api/schedules/{schedule_id}/enable/')
        self.assertEqual(en.status_code, 200)
        self.assertTrue(en.data['enabled'])

        # Disable
        dis = self.client.post(f'/api/schedules/{schedule_id}/disable/')
        self.assertEqual(dis.status_code, 200)
        self.assertFalse(dis.data['enabled'])

    def test_cron_schedule_creation(self):
        payload = {
            'name': 'Service map nightly',
            'job_key': 'service_map',
            'enabled': True,
            'schedule_type': 'cron',
            'cron_expr': '0 2 * * *',
            'timezone': 'UTC',
        }
        resp = self.client.post('/api/schedules/', payload, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['schedule_type'], 'cron')
        self.assertTrue(resp.data['next_run_at'])
