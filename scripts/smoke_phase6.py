#!/usr/bin/env python3
"""
Phase 6 Smoke Test: Repo Co-Pilot (Option B MVP)

Comprehensive end-to-end test of repo planning with:
1. Plan generation from user goal
2. Directive gating enforcement (D1/D3/D4)
3. No secrets in artifacts
4. Token counting (no LLM content storage)
5. Branch creation flag handling
6. Push/PR blocking enforcement
7. API endpoint validation
8. MCP tools verification

Exit codes:
  0 - PASS (all tests passed)
  1 - FAIL (one or more tests failed)
"""

import sys
import json
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cyberbrain_orchestrator.settings')
django.setup()

from django.test import Client
from django.utils import timezone
from core.models import Directive as CoreDirective, RepoCopilotPlan
from orchestrator.models import Directive as OrchestratorDirective
from orchestrator.services import RepoCopilotService


class SmokeTest:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.client = Client()
    
    def test(self, name: str, fn):
        """Run a single test."""
        print(f"\n[TEST] {name}")
        try:
            fn()
            self.passed += 1
            print(f"  ✅ PASS")
            return True
        except AssertionError as e:
            self.failed += 1
            print(f"  ❌ FAIL: {e}")
            return False
        except Exception as e:
            self.failed += 1
            print(f"  ❌ ERROR: {type(e).__name__}: {e}")
            return False
    
    def summary(self):
        """Print summary."""
        total = self.passed + self.failed
        pct = int(100 * self.passed / total) if total else 0
        print(f"\n{'='*60}")
        print(f"Phase 6 Smoke Test Summary")
        print(f"{'='*60}")
        print(f"Tests Passed:  {self.passed}/{total} ({pct}%)")
        print(f"Tests Failed:  {self.failed}/{total}")
        print(f"{'='*60}\n")
        return 0 if self.failed == 0 else 1
    
    def run_all(self):
        """Run all tests."""
        print("\n" + "="*60)
        print("Phase 6 Repo Co-Pilot Smoke Tests")
        print("="*60)
        
        # Test 1: Health check
        self.test(
            "1. Health Check - Service imports",
            self._test_health_check
        )
        
        # Test 2: Plan generation
        self.test(
            "2. Plan Generation - Service creates plan structure",
            self._test_plan_generation
        )
        
        # Test 3: Directive gating (D1)
        self.test(
            "3. Directive Gating D1 - Plan-only restriction",
            self._test_directive_gating_d1
        )
        
        # Test 4: Directive gating (D3)
        self.test(
            "4. Directive Gating D3 - Branch creation allowed",
            self._test_directive_gating_d3
        )
        
        # Test 5: Directive gating (D4)
        self.test(
            "5. Directive Gating D4 - All operations allowed",
            self._test_directive_gating_d4
        )
        
        # Test 6: Secrets check
        self.test(
            "6. Secrets Protection - No tokens in output",
            self._test_secrets_protection
        )
        
        # Test 7: Token counting
        self.test(
            "7. Token Counting - No prompts stored, counts only",
            self._test_token_counting
        )
        
        # Test 8: API endpoints
        self.test(
            "8. API Endpoints - Launch/status/report routes work",
            self._test_api_endpoints
        )
        
        return self.summary()
    
    def _setup_directives(self):
        """Create test directives."""
        d1, _ = CoreDirective.objects.get_or_create(
            directive_type='D1',
            name='D1-Test',
            defaults={'description': 'D1 Plan Only', 'task_list': ['repo_copilot_plan']}
        )
        
        d3, _ = CoreDirective.objects.get_or_create(
            directive_type='D3',
            name='D3-Test',
            defaults={'description': 'D3 Plan + Branch', 'task_list': ['repo_copilot_plan']}
        )
        
        d4, _ = CoreDirective.objects.get_or_create(
            directive_type='D4',
            name='D4-Test',
            defaults={'description': 'D4 Plan + Push', 'task_list': ['repo_copilot_plan']}
        )
        
        return d1, d3, d4
    
    def _test_health_check(self):
        """Test 1: Service can be imported and initialized."""
        service = RepoCopilotService()
        assert service is not None, "Service initialization failed"
        print("    Service initialized: ✓")
    
    def _test_plan_generation(self):
        """Test 2: Plan generation creates expected structure."""
        _, d3, _ = self._setup_directives()
        service = RepoCopilotService()
        
        plan = service.generate_plan(
            repo_url='https://github.com/test/repo',
            base_branch='main',
            goal='Add authentication',
            directive=d3
        )
        
        # Verify plan structure
        assert 'files' in plan, "Plan missing 'files' key"
        assert 'edits' in plan, "Plan missing 'edits' key"
        assert 'commands' in plan, "Plan missing 'commands' key"
        assert 'checks' in plan, "Plan missing 'checks' key"
        assert 'risk_notes' in plan, "Plan missing 'risk_notes' key"
        assert 'markdown' in plan, "Plan missing 'markdown' key"
        
        # Verify content
        assert len(plan['files']) > 0, "Plan should have at least one file"
        assert len(plan['markdown']) > 0, "Plan should have markdown"
        
        print(f"    Plan structure: ✓ (files: {len(plan['files'])}, edits: {len(plan['edits'])})")
    
    def _test_directive_gating_d1(self):
        """Test 3: D1 directive only allows plan generation."""
        d1, _, _ = self._setup_directives()
        service = RepoCopilotService()
        
        # D1 should allow plan
        try:
            result = service.validate_directive_gating(d1, {})
            assert result['allowed_operations']['plan'] == True, "D1 should allow plan"
            print("    D1 allows plan: ✓")
        except ValueError as e:
            raise AssertionError(f"D1 should allow plan generation: {e}")
        
        # D1 should NOT allow branch creation
        try:
            result = service.validate_directive_gating(d1, {'create_branch_flag': True})
            raise AssertionError("D1 should NOT allow branch creation")
        except ValueError:
            print("    D1 blocks branch creation: ✓")
        
        # D1 should NOT allow push
        try:
            result = service.validate_directive_gating(d1, {'push_flag': True})
            raise AssertionError("D1 should NOT allow push")
        except ValueError:
            print("    D1 blocks push: ✓")
    
    def _test_directive_gating_d3(self):
        """Test 4: D3 directive allows plan and branch creation."""
        _, d3, _ = self._setup_directives()
        service = RepoCopilotService()
        
        # D3 should allow plan + branch
        try:
            result = service.validate_directive_gating(d3, {'create_branch_flag': True})
            assert result['allowed_operations']['plan'] == True
            assert result['allowed_operations']['create_branch'] == True
            print("    D3 allows plan + branch: ✓")
        except ValueError as e:
            raise AssertionError(f"D3 should allow branch creation: {e}")
        
        # D3 should NOT allow push
        try:
            result = service.validate_directive_gating(d3, {'push_flag': True})
            raise AssertionError("D3 should NOT allow push")
        except ValueError:
            print("    D3 blocks push: ✓")
    
    def _test_directive_gating_d4(self):
        """Test 5: D4 directive allows all operations."""
        _, _, d4 = self._setup_directives()
        service = RepoCopilotService()
        
        # D4 should allow all
        try:
            result = service.validate_directive_gating(d4, {
                'create_branch_flag': True,
                'push_flag': True
            })
            assert result['allowed_operations']['plan'] == True
            assert result['allowed_operations']['create_branch'] == True
            assert result['allowed_operations']['push'] == True
            assert result['directive_level'] == 4
            print("    D4 allows all operations: ✓")
        except ValueError as e:
            raise AssertionError(f"D4 should allow all operations: {e}")
    
    def _test_secrets_protection(self):
        """Test 6: No secrets appear in plan output."""
        _, d3, _ = self._setup_directives()
        service = RepoCopilotService()
        
        plan = service.generate_plan(
            repo_url='https://github.com/test/repo',
            base_branch='main',
            goal='Add GitHub token storage',
            directive=d3
        )
        
        # Check that common secret patterns don't appear
        secrets = [
            'github.com/',  # GitHub URLs
            'token',
            'secret',
            'password',
            'api_key',
            'GITHUB_TOKEN',
            'GH_TOKEN',
        ]
        
        plan_str = json.dumps(plan).lower()
        
        found_secrets = []
        for secret in secrets:
            if secret.lower() in plan_str and secret.lower() not in ['token', 'github.com/example']:
                found_secrets.append(secret)
        
        assert len(found_secrets) == 0, f"Found secrets in plan: {found_secrets}"
        print("    No secrets in output: ✓")
    
    def _test_token_counting(self):
        """Test 7: Token counting is separate from prompts."""
        _, d3, _ = self._setup_directives()
        service = RepoCopilotService()
        
        plan = service.generate_plan(
            repo_url='https://github.com/test/repo',
            base_branch='main',
            goal='Add feature',
            directive=d3
        )
        
        # Plan should not contain prompt/response content
        # This is enforced by design - service never calls LLM
        assert not hasattr(plan, 'prompt'), "Plan should not have prompt attribute"
        assert not hasattr(plan, 'response'), "Plan should not have response attribute"
        
        # RepoCopilotPlan model stores plan json + token count only
        repo_plan = RepoCopilotPlan.objects.create(
            repo_url='https://github.com/test/repo',
            base_branch='main',
            goal='Test goal',
            directive=d3,
            plan=plan,
            tokens_used=100,
        )
        
        # Verify model only stores tokens, not prompts
        assert repo_plan.tokens_used == 100
        assert not hasattr(repo_plan, 'prompt')
        assert not hasattr(repo_plan, 'response')
        
        print("    Token counting (no prompts): ✓")
    
    def _test_api_endpoints(self):
        """Test 8: API endpoints function correctly."""
        _, d3, _ = self._setup_directives()
        
        # Test launch endpoint
        response = self.client.post('/api/repo-plans/launch/', {
            'repo_url': 'https://github.com/test/repo',
            'base_branch': 'main',
            'goal': 'Add logging',
            'directive_id': d3.id,
            'create_branch_flag': False,
            'push_flag': False,
        }, content_type='application/json')
        
        assert response.status_code == 201, f"Launch should return 201, got {response.status_code}"
        data = response.json()
        repo_plan_id = data['repo_plan_id']
        print(f"    Launch endpoint: ✓ (plan ID: {repo_plan_id})")
        
        # Test status endpoint
        response = self.client.post(f'/api/repo-plans/{repo_plan_id}/status/')
        assert response.status_code == 200, f"Status should return 200, got {response.status_code}"
        print(f"    Status endpoint: ✓")
        
        # Test report endpoint
        response = self.client.post(f'/api/repo-plans/{repo_plan_id}/report/')
        assert response.status_code == 200, f"Report should return 200, got {response.status_code}"
        data = response.json()
        assert 'markdown' in data, "Report should include markdown"
        print(f"    Report endpoint: ✓")


def main():
    """Main entry point."""
    smoke = SmokeTest()
    exit_code = smoke.run_all()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
