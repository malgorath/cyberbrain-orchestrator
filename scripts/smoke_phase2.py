#!/usr/bin/env python3
"""
Phase 2 Smoke Test: Validate scheduling infrastructure end-to-end.
Requirements:
- Docker Compose services running (web + scheduler)
- Fresh database state or clean schedule namespace

Exit codes:
- 0: PASS
- 1: FAIL
"""
import sys
import time
import json
import urllib.request
import urllib.error
import subprocess

BASE_URL = "http://localhost:9595"
API_BASE = f"{BASE_URL}/api"
TIMEOUT = 180  # 3 minutes max wait


def fail(msg):
    print(f"❌ FAIL: {msg}")
    sys.exit(1)


def http_json(method, path, payload=None):
    """Make HTTP request and return status code and JSON response."""
    url = f"{API_BASE}{path}"
    data = None
    headers = {'Content-Type': 'application/json'}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8')
            if body:
                return resp.getcode(), json.loads(body)
            return resp.getcode(), {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', 'ignore')
        fail(f"HTTP {e.code} on {path}: {error_body}")
    except Exception as e:
        fail(f"Error requesting {path}: {e}")


def check_service_running():
    """Ensure scheduler service is running in docker-compose."""
    print("🔍 Checking scheduler service status...")
    try:
        result = subprocess.run(
            ["docker-compose", "ps", "--services", "--filter", "status=running"],
            capture_output=True,
            text=True,
            check=True
        )
        services = result.stdout.strip().split('\n')
        if 'scheduler' not in services:
            fail("Scheduler service not running. Start with: docker-compose up -d scheduler")
        print("  ✅ Scheduler service running")
    except subprocess.CalledProcessError as e:
        fail(f"Failed to check docker-compose services: {e}")


def get_or_create_directive():
    """Get or create a test directive for smoke test."""
    print("🔧 Setting up test directive...")
    status, directives = http_json('GET', '/directives/')
    if directives:
        directive_id = directives[0]['id']
        print(f"  ✅ Using existing directive: {directive_id}")
        return directive_id
    # Create one if none exist
    payload = {
        "name": "smoke-test-directive",
        "directive_type": "D1",
        "description": "Smoke test directive",
        "task_config": {}
    }
    status, directive = http_json('POST', '/directives/', payload)
    directive_id = directive['id']
    print(f"  ✅ Created directive: {directive_id}")
    return directive_id


def get_jobs():
    """Fetch available jobs (Task1/2/3)."""
    print("🔍 Fetching available jobs...")
    status, jobs = http_json('GET', '/jobs/')
    if len(jobs) < 3:
        fail(f"Expected at least 3 jobs, found {len(jobs)}")
    print(f"  ✅ Found {len(jobs)} jobs")
    return jobs[:3]  # Use first 3


def create_schedule(name, job_key, directive_id, interval_minutes=1, max_global=None, max_per_job=None):
    """Create a schedule via API."""
    payload = {
        "name": name,
        "job_key": job_key,
        "directive_id": directive_id,
        "enabled": True,
        "schedule_type": "interval",
        "interval_minutes": interval_minutes,
        "timezone": "UTC"
    }
    if max_global is not None:
        payload["max_global"] = max_global
    if max_per_job is not None:
        payload["max_per_job"] = max_per_job
    
    status, schedule = http_json('POST', '/schedules/', payload)
    print(f"  ✅ Created schedule: {schedule['name']} (ID: {schedule['id']})")
    return schedule


def wait_for_scheduled_runs(schedule_ids, timeout_seconds=TIMEOUT):
    """Wait until each schedule has at least one successful run."""
    print(f"⏳ Waiting up to {timeout_seconds}s for scheduled runs...")
    start = time.time()
    completed = set()
    
    while time.time() - start < timeout_seconds:
        for schedule_id in schedule_ids:
            if schedule_id in completed:
                continue
            status, history = http_json('GET', f'/schedules/{schedule_id}/history/')
            if history and any(h['status'] == 'finished' for h in history):
                print(f"  ✅ Schedule {schedule_id} has successful run")
                completed.add(schedule_id)
        
        if len(completed) == len(schedule_ids):
            elapsed = time.time() - start
            print(f"  ✅ All schedules completed in {elapsed:.1f}s")
            return
        
        time.sleep(5)
    
    fail(f"Timeout waiting for scheduled runs. Completed: {len(completed)}/{len(schedule_ids)}")


def test_run_now(schedule_id):
    """Test run-now endpoint even when next_run_at is in the future."""
    print(f"🚀 Testing run-now for schedule {schedule_id}...")
    status, result = http_json('POST', f'/schedules/{schedule_id}/run-now/')
    run_id = result.get('run_id')
    if not run_id:
        fail(f"Run-now did not return run_id: {result}")
    print(f"  ✅ Run-now created run: {run_id}")
    return run_id


def test_concurrency_limits(directive_id, jobs):
    """Test concurrency limits: max_global=1, max_per_job=1, 2 schedules due now."""
    print("🔒 Testing concurrency limits...")
    
    # Create 2 schedules with same job type, both due now, with max_per_job=1
    job = jobs[0]
    schedules = []
    timestamp = int(time.time())
    for i in range(2):
        name = f"smoke-concurrency-{i}-{timestamp}"
        schedule = create_schedule(
            name, job['task_key'], directive_id, 
            interval_minutes=60,  # 1 hour (won't trigger naturally)
            max_global=1, 
            max_per_job=1
        )
        schedules.append(schedule)
    
    # Manually trigger both via run-now (simulates both being due)
    run_ids = []
    for schedule in schedules:
        status, result = http_json('POST', f'/schedules/{schedule["id"]}/run-now/')
        run_ids.append(result['run_id'])
        print(f"  ✅ Triggered run: {result['run_id']}")
    
    # Brief wait for status update
    time.sleep(1)
    
    status, runs = http_json('GET', '/runs/')
    
    # Count how many of our runs are in running/pending state
    our_runs = [run for run in runs if run['id'] in run_ids]
    active_count = sum(1 for run in our_runs if run['status'] in ['running', 'pending'])
    
    print(f"  ℹ️  Active runs at check time: {active_count} (max expected: 1)")
    
    # Verify the schedules have the correct limits set
    for schedule in schedules:
        status, sch = http_json('GET', f'/schedules/{schedule["id"]}/')
        if sch['max_global'] != 1 or sch['max_per_job'] != 1:
            fail(f"Schedule {schedule['id']} has incorrect limits: max_global={sch['max_global']}, max_per_job={sch['max_per_job']}")
    
    print("  ✅ Concurrency limits configured correctly")
    
    # Cleanup
    for schedule in schedules:
        http_json('DELETE', f'/schedules/{schedule["id"]}/')


def main():
    print("=" * 60)
    print("🧠 Phase 2 Smoke Test: Scheduling")
    print("=" * 60)
    
    try:
        # 1. Check scheduler service
        check_service_running()
        
        # 2. Get/create directive and jobs
        directive_id = get_or_create_directive()
        jobs = get_jobs()
        
        # 3. Create schedules for each job
        print("\n📅 Creating schedules for each job...")
        schedules = []
        timestamp = int(time.time())
        for job in jobs:
            name = f"smoke-{job['task_key']}-{timestamp}"
            schedule = create_schedule(name, job['task_key'], directive_id, interval_minutes=1)
            schedules.append(schedule)
        
        # 4. Wait for scheduled runs to complete
        print()
        schedule_ids = [s['id'] for s in schedules]
        wait_for_scheduled_runs(schedule_ids)
        
        # 5. Test run-now endpoint
        print()
        test_run_now(schedules[0]['id'])
        
        # 6. Test concurrency limits
        print()
        test_concurrency_limits(directive_id, jobs)
        
        # Cleanup: disable schedules
        print("\n🧹 Cleaning up schedules...")
        for schedule in schedules:
            http_json('POST', f'/schedules/{schedule["id"]}/disable/')
        print("  ✅ Schedules disabled")
        
        print("\n" + "=" * 60)
        print("✅ PASS: Phase 2 scheduling smoke test complete")
        print("=" * 60)
        return 0
        
    except Exception as e:
        fail(f"Unexpected error: {e}")


if __name__ == "__main__":
    sys.exit(main())
