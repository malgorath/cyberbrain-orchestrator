"""
E3 Acceptance Tests: MCP Control-Plane API (Streamable HTTP + SSE)

Verifies:
1. MCP endpoint responds at /mcp with tool manifest
2. launch_run creates Run with directive snapshot (no LLM content)
3. get_run_report returns markdown/JSON summaries + token totals (NO prompts/responses)
4. Token-only storage enforced (no prompt/response fields)
5. get_allowlist / set_allowlist manage container whitelist
"""
import json
from django.test import TestCase, Client
from core.models import Directive, Job, Run, LLMCall, ContainerAllowlist


def parse_sse_response(response):
    """Extract JSON from single-event SSE response."""
    data = b"".join(response.streaming_content).decode("utf-8")
    if not data.startswith("data: "):
        raise ValueError(f"Invalid SSE format: {data}")
    payload = data[len("data: "):].strip()
    return json.loads(payload)


class E3MCPControlPlaneAcceptanceTest(TestCase):
    """Control-plane MCP endpoint acceptance tests."""
    
    def setUp(self):
        """Create test fixtures."""
        self.client = Client()
        
        # Create D1 directive
        self.directive_d1 = Directive.objects.create(
            directive_type='D1',
            name='Log Triage (D1)',
            description='Default log triage directive',
            directive_text='Analyze application logs for errors and warnings',
            is_builtin=True,
        )
        
        # Create log_triage job
        self.job = Job.objects.create(
            task_key='log_triage',
            name='Log Triage Job',
            description='Triage application logs',
            default_directive=self.directive_d1,
            config={'since_last_successful_run': True},
        )
    
    def test_mcp_manifest_lists_tools(self):
        """GET /mcp returns tool manifest with all required tools."""
        response = self.client.get('/mcp')
        self.assertEqual(response.status_code, 200)
        
        manifest = response.json()
        self.assertEqual(manifest['transport'], 'sse')
        self.assertIn('tools', manifest)
        
        tool_names = [t['name'] for t in manifest['tools']]
        required_tools = [
            'launch_run', 'list_runs', 'get_run', 'get_run_report',
            'list_directives', 'get_directive',
            'get_allowlist', 'set_allowlist'
        ]
        for tool in required_tools:
            self.assertIn(tool, tool_names)
    
    def test_launch_run_creates_run_with_directive_snapshot(self):
        """launch_run tool creates Run with directive snapshot (no LLM content)."""
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'launch_run',
                'params': {
                    'job_id': self.job.id,
                    'directive_id': self.directive_d1.id,
                },
            }),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 200)
        payload = parse_sse_response(response)
        self.assertTrue(payload.get('ok'))
        
        # Verify Run was created
        self.assertEqual(Run.objects.count(), 1)
        run = Run.objects.first()
        self.assertEqual(run.job.id, self.job.id)
        self.assertEqual(run.status, 'pending')
        
        # Verify directive snapshot (name + text only, NO LLM content)
        self.assertEqual(run.directive_snapshot_name, self.directive_d1.name)
        self.assertEqual(run.directive_snapshot_text, self.directive_d1.directive_text)
        
        # Token fields exist but are zero (no LLM calls yet)
        self.assertEqual(run.token_prompt, 0)
        self.assertEqual(run.token_completion, 0)
        self.assertEqual(run.token_total, 0)
    
    def test_launch_run_with_task_key(self):
        """launch_run can resolve job via task_key (not just job_id)."""
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'launch_run',
                'params': {
                    'task_key': 'log_triage',  # Resolve job by task key
                    'directive_id': self.directive_d1.id,
                },
            }),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 200)
        payload = parse_sse_response(response)
        self.assertTrue(payload.get('ok'))
        self.assertEqual(Run.objects.count(), 1)
    
    def test_launch_run_with_custom_directive_text(self):
        """launch_run accepts custom_directive_text instead of directive_id."""
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'launch_run',
                'params': {
                    'job_id': self.job.id,
                    'custom_directive_text': 'Custom analysis instructions',
                },
            }),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 200)
        payload = parse_sse_response(response)
        self.assertTrue(payload.get('ok'))
        
        run = Run.objects.first()
        self.assertEqual(run.directive_snapshot_name, 'custom')
        self.assertEqual(run.directive_snapshot_text, 'Custom analysis instructions')
    
    def test_get_run_report_returns_token_totals_no_content(self):
        """get_run_report returns markdown/JSON summaries + token totals (NO prompts/responses)."""
        # Create a completed run with token usage
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name='D1',
            directive_snapshot_text='Test directive',
            status='success',
            report_markdown='# Analysis Complete\n\nSummary of findings.',
            report_json={'error_count': 5, 'warning_count': 12},
            token_prompt=100,
            token_completion=250,
            token_total=350,
        )
        
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'get_run_report',
                'params': {'run_id': run.id},
            }),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 200)
        payload = parse_sse_response(response)
        
        self.assertEqual(payload['run_id'], run.id)
        self.assertIn('# Analysis Complete', payload['markdown'])
        self.assertEqual(payload['summary']['error_count'], 5)
        self.assertEqual(payload['total_tokens'], 350)
        
        # Verify NO prompt/response content in payload
        self.assertNotIn('prompt_content', payload)
        self.assertNotIn('response_content', payload)
    
    def test_list_runs_filters_by_status(self):
        """list_runs returns runs and respects status filter."""
        # Create success run
        success_run = Run.objects.create(
            job=self.job,
            directive_snapshot_name='D1',
            directive_snapshot_text='test',
            status='success',
        )
        
        # Create pending run
        pending_run = Run.objects.create(
            job=self.job,
            directive_snapshot_name='D1',
            directive_snapshot_text='test',
            status='pending',
        )
        
        # List all
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'list_runs',
                'params': {},
            }),
            content_type='application/json',
        )
        
        payload = parse_sse_response(response)
        self.assertEqual(len(payload['runs']), 2)
        
        # Filter by success
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'list_runs',
                'params': {'status': 'success'},
            }),
            content_type='application/json',
        )
        
        payload = parse_sse_response(response)
        self.assertEqual(len(payload['runs']), 1)
        self.assertEqual(payload['runs'][0]['status'], 'success')
    
    def test_get_run_detail(self):
        """get_run returns full run detail."""
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name='D1',
            directive_snapshot_text='test',
            status='pending',
        )
        
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'get_run',
                'params': {'run_id': run.id},
            }),
            content_type='application/json',
        )
        
        payload = parse_sse_response(response)
        self.assertEqual(payload['run']['id'], run.id)
        self.assertEqual(payload['run']['status'], 'pending')
    
    def test_list_directives(self):
        """list_directives returns all directive definitions."""
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'list_directives',
                'params': {},
            }),
            content_type='application/json',
        )
        
        payload = parse_sse_response(response)
        self.assertGreaterEqual(len(payload['directives']), 1)
        directive = payload['directives'][0]
        self.assertIn('id', directive)
        self.assertIn('name', directive)
        self.assertIn('directive_type', directive)
    
    def test_get_directive(self):
        """get_directive returns single directive."""
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'get_directive',
                'params': {'directive_id': self.directive_d1.id},
            }),
            content_type='application/json',
        )
        
        payload = parse_sse_response(response)
        self.assertEqual(payload['directive']['id'], self.directive_d1.id)
        self.assertEqual(payload['directive']['name'], self.directive_d1.name)
    
    def test_set_allowlist_upserts_container(self):
        """set_allowlist creates or updates container allowlist entry."""
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'set_allowlist',
                'params': {
                    'container_id': 'abc123def456',
                    'container_name': 'my-app',
                    'enabled': True,
                },
            }),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 200)
        payload = parse_sse_response(response)
        
        # Verify entry was created
        entry = ContainerAllowlist.objects.get(container_id='abc123def456')
        self.assertEqual(entry.container_name, 'my-app')
        self.assertTrue(entry.enabled)
    
    def test_get_allowlist_shows_enabled(self):
        """get_allowlist returns enabled container entries."""
        ContainerAllowlist.objects.create(
            container_id='abc123',
            container_name='allowed-app',
            enabled=True,
        )
        
        ContainerAllowlist.objects.create(
            container_id='def456',
            container_name='blocked-app',
            enabled=False,
        )
        
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'get_allowlist',
                'params': {},
            }),
            content_type='application/json',
        )
        
        payload = parse_sse_response(response)
        # Should only show enabled entries
        self.assertEqual(len(payload['allowlist']), 1)
        self.assertEqual(payload['allowlist'][0]['container_name'], 'allowed-app')
    
    def test_token_only_storage_enforced(self):
        """Verify token fields exist and no prompt/response fields are created."""
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name='D1',
            directive_snapshot_text='test',
            status='success',
            token_prompt=100,
            token_completion=50,
            token_total=150,
        )
        
        # Create LLMCall with token counts only
        llm_call = LLMCall.objects.create(
            run=run,
            worker_id='worker-1',
            endpoint='vllm',
            model_id='llama-2-7b',
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        
        # Verify NO prompt/response fields exist
        self.assertFalse(hasattr(llm_call, 'prompt_content'))
        self.assertFalse(hasattr(llm_call, 'response_content'))
        
        # Verify token fields exist
        self.assertEqual(llm_call.prompt_tokens, 100)
        self.assertEqual(llm_call.completion_tokens, 50)
        self.assertEqual(llm_call.total_tokens, 150)
    
    def test_mcp_requires_valid_json(self):
        """POST /mcp with invalid JSON returns error."""
        response = self.client.post(
            '/mcp',
            data='invalid json {',
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 400)
        payload = parse_sse_response(response)
        self.assertIn('error', payload)
    
    def test_mcp_unknown_tool_returns_error(self):
        """POST /mcp with unknown tool returns error."""
        response = self.client.post(
            '/mcp',
            data=json.dumps({
                'tool': 'nonexistent_tool',
                'params': {},
            }),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 400)
        payload = parse_sse_response(response)
        self.assertIn('error', payload)
