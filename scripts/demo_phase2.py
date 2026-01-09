#!/usr/bin/env python3
"""
Phase 2 Scheduler Quick Demo

Demonstrates the scheduler execution path:
1. Create a schedule via API
2. Show scheduler picks it up automatically
3. Show run-now endpoint
4. Show concurrency limits

This is a demo script, not a test. For validation, use smoke_phase2.py
"""
import requests
import time
import json

BASE_URL = "http://localhost:9595"

def demo():
    print("="*60)
    print("Phase 2 Scheduler Quick Demo")
    print("="*60)
    
    # 1. Create a schedule
    print("\n1. Creating schedule (log_triage every 1 minute)...")
    schedule_data = {
        'name': 'demo-schedule',
        'job_key': 'log_triage',
        'enabled': True,
        'schedule_type': 'interval',
        'interval_minutes': 1,
        'timezone': 'UTC',
        'max_global': 2,
        'max_per_job': 1
    }
    
    resp = requests.post(f"{BASE_URL}/api/schedules/", json=schedule_data)
    if resp.status_code == 201:
        schedule = resp.json()
        schedule_id = schedule['id']
        print(f"✓ Schedule created: ID={schedule_id}")
        print(f"  next_run_at: {schedule.get('next_run_at')}")
    else:
        print(f"✗ Failed to create schedule: {resp.status_code}")
        print(resp.text)
        return
    
    # 2. Show schedule will execute automatically
    print("\n2. Scheduler will execute this automatically...")
    print("   (Check scheduler logs: docker-compose logs -f scheduler)")
    print("   Waiting 10 seconds to give scheduler time...")
    time.sleep(10)
    
    # 3. Check history
    print("\n3. Checking schedule history...")
    resp = requests.get(f"{BASE_URL}/api/schedules/{schedule_id}/history/")
    if resp.status_code == 200:
        history = resp.json()
        if history['count'] > 0:
            print(f"✓ Found {history['count']} run(s) in history")
            for item in history['items'][:3]:
                print(f"   - Run {item['run_id']}: {item['status']} (started: {item['started_at']})")
        else:
            print("⚠ No runs yet (scheduler may not be running)")
    
    # 4. Test run-now
    print("\n4. Testing run-now endpoint...")
    resp = requests.post(f"{BASE_URL}/api/schedules/{schedule_id}/run-now/")
    if resp.status_code == 201:
        run_data = resp.json()
        run_id = run_data['run_id']
        print(f"✓ Run-now triggered: run_id={run_id}")
        
        # Wait and check run status
        time.sleep(2)
        resp = requests.get(f"{BASE_URL}/api/runs/{run_id}/")
        if resp.status_code == 200:
            run = resp.json()
            print(f"  Run status: {run['status']}")
            print(f"  Jobs: {len(run.get('jobs', []))}")
    else:
        print(f"✗ Run-now failed: {resp.status_code}")
    
    # 5. Show schedule details
    print("\n5. Final schedule state...")
    resp = requests.get(f"{BASE_URL}/api/schedules/{schedule_id}/")
    if resp.status_code == 200:
        schedule = resp.json()
        print(f"  last_run_at: {schedule.get('last_run_at')}")
        print(f"  next_run_at: {schedule.get('next_run_at')}")
        print(f"  enabled: {schedule.get('enabled')}")
    
    # 6. Cleanup
    print("\n6. Cleaning up...")
    resp = requests.delete(f"{BASE_URL}/api/schedules/{schedule_id}/")
    if resp.status_code == 204:
        print("✓ Schedule deleted")
    
    print("\n" + "="*60)
    print("Demo complete!")
    print("="*60)
    print("\nKey Points:")
    print("- Scheduler automatically executes due schedules")
    print("- Uses SAME internal path as manual runs")
    print("- Enforces concurrency limits (max_global, max_per_job)")
    print("- Run-now creates run immediately")
    print("- Token counts only (no prompt/response storage)")
    print("\nFor full validation, run: python3 scripts/smoke_phase2.py")

if __name__ == '__main__':
    try:
        demo()
    except requests.exceptions.ConnectionError:
        print("\n✗ Service not reachable at http://localhost:9595")
        print("Start services with: docker-compose up -d")
        print("Start scheduler with: docker-compose up -d scheduler")
