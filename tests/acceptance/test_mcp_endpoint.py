from django.test import TestCase
from rest_framework.test import APIClient


class McpEndpointAcceptanceTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_mcp_get_tools(self):
        resp = self.client.get('/mcp')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # SSE preferred transport
        self.assertIn(data.get('transport'), ('sse', 'http'))
        tools = [t.get('name') for t in data.get('tools', [])]
        required = [
            'launch_run',
            'list_runs',
            'get_run',
            'get_run_report',
            'list_directives',
            'get_allowlist',
            'set_allowlist',
        ]
        for name in required:
            self.assertIn(name, tools)
