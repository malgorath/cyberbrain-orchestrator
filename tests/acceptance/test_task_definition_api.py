from django.test import TestCase
from rest_framework.test import APIClient


class TaskDefinitionApiAcceptanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_task_definition_crud(self):
        payload = {
            'key': 'log_triage',
            'name': 'Log Triage',
            'description': 'Analyze logs',
            'enabled': True,
            'default_config': {'since_last_successful_run': True},
        }
        create_resp = self.client.post('/api/tasks/', payload, format='json')
        self.assertEqual(create_resp.status_code, 201)
        task_id = create_resp.data['id']
        self.assertEqual(create_resp.data['key'], 'log_triage')

        update_payload = {
            'key': 'log_triage',
            'name': 'Log Triage Updated',
            'description': 'Updated description',
            'enabled': False,
            'default_config': {'since_last_successful_run': False},
        }
        update_resp = self.client.put(f'/api/tasks/{task_id}/', update_payload, format='json')
        self.assertEqual(update_resp.status_code, 200)
        self.assertFalse(update_resp.data['enabled'])

        list_resp = self.client.get('/api/tasks/')
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.data if isinstance(list_resp.data, list) else list_resp.data.get('results', [])
        self.assertTrue(any(x['id'] == task_id for x in items))
