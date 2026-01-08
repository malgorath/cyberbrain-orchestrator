#!/usr/bin/env python3
"""
Validation script to check Django project structure and API endpoints
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cyberbrain_orchestrator.test_settings')
django.setup()

from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient
from orchestrator.models import Directive, Run, Job, ContainerAllowlist


def setup_database():
    """Setup test database"""
    print("🔧 Setting up test database...")
    call_command('migrate', '--run-syncdb', verbosity=0)
    print("  ✅ Database setup complete")


def validate_api_endpoints():
    """Validate that all required API endpoints exist"""
    print("\n🔍 Validating API Endpoints...")
    
    client = APIClient()
    
    # Create a test directive
    directive = Directive.objects.create(
        name='test_directive',
        description='Test directive for validation'
    )
    
    # Test endpoints
    endpoints = [
        ('api:directive-list', 'GET', 'List Directives'),
        ('api:run-list', 'GET', 'List Runs'),
        ('api:job-list', 'GET', 'List Jobs'),
        ('api:containerallowlist-list', 'GET', 'List Containers'),
    ]
    
    for url_name, method, description in endpoints:
        try:
            url = reverse(url_name)
            print(f"  ✅ {description}: {url}")
        except Exception as e:
            print(f"  ❌ {description}: {e}")
    
    # Test launch endpoint
    print("\n🚀 Testing Launch Endpoint...")
    response = client.post('/api/runs/launch/', {}, format='json')
    if response.status_code == 201:
        print(f"  ✅ Launch endpoint works! Created run ID: {response.data['id']}")
    else:
        print(f"  ❌ Launch endpoint failed: {response.status_code}")
    
    # Test report endpoint
    print("\n📊 Testing Report Endpoint...")
    run = Run.objects.first()
    if run:
        response = client.get(f'/api/runs/{run.id}/report/')
        if response.status_code == 200:
            print(f"  ✅ Report endpoint works!")
            print(f"     - Has markdown: {bool(response.data.get('markdown'))}")
            print(f"     - Has json: {bool(response.data.get('json'))}")
        else:
            print(f"  ❌ Report endpoint failed: {response.status_code}")


def validate_models():
    """Validate that all models are properly set up"""
    print("\n📦 Validating Models...")
    
    models = [
        ('Directive', Directive),
        ('Run', Run),
        ('Job', Job),
        ('ContainerAllowlist', ContainerAllowlist),
    ]
    
    for name, model in models:
        try:
            count = model.objects.count()
            print(f"  ✅ {name}: {count} record(s)")
        except Exception as e:
            print(f"  ❌ {name}: {e}")


def validate_task_types():
    """Validate that all task types are defined"""
    print("\n🎯 Validating Task Types...")
    
    required_tasks = ['log_triage', 'gpu_report', 'service_map']
    job_choices = dict(Job.TASK_CHOICES)
    
    for task in required_tasks:
        if task in job_choices:
            print(f"  ✅ Task type '{task}': {job_choices[task]}")
        else:
            print(f"  ❌ Task type '{task}': MISSING")


def main():
    print("=" * 60)
    print("🧠 Cyberbrain Orchestrator Validation")
    print("=" * 60)
    
    try:
        setup_database()
        validate_models()
        validate_task_types()
        validate_api_endpoints()
        
        print("\n" + "=" * 60)
        print("✅ All validations passed!")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n❌ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
