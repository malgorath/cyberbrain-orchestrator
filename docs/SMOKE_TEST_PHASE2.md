# Phase 2 Smoke Test

## Purpose
Validates Phase 2 scheduling infrastructure end-to-end in a running environment.

## Prerequisites
- Docker Compose services running (`docker-compose up -d`)
- Both `web` and `scheduler` services must be running
- API accessible at `http://localhost:9595/api/`

## How to Run

### Command Line
```bash
python scripts/smoke_phase2.py
```

### VS Code Task
Use the task: **Phase 2: Smoke Test**
- Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
- Type: "Tasks: Run Task"
- Select: "Phase 2: Smoke Test"

### Docker Container
```bash
docker-compose exec web python scripts/smoke_phase2.py
```

## What Gets Tested

1. **Scheduler Service**: Confirms scheduler container is running
2. **Schedule Creation**: Creates interval schedules for each job type (Task1/2/3)
3. **Automatic Execution**: Waits up to 3 minutes for scheduler to trigger runs
4. **Run Now Endpoint**: Tests manual run triggering via `/api/schedules/{id}/run-now/`
5. **Concurrency Limits**: Validates `max_global` and `max_per_job` constraints

## PASS Criteria

The test prints `✅ PASS` and exits with code 0 when:
- Scheduler service is running in Docker Compose
- Schedules are created successfully via API
- Each schedule produces at least one successful run within 3 minutes
- Run-now endpoint creates a run immediately
- Concurrency limits (`max_global=1`, `max_per_job=1`) are configured correctly

## FAIL Criteria

The test prints `❌ FAIL` and exits with code 1 if:
- Scheduler service is not running
- API endpoints return errors
- Scheduled runs do not complete within 3 minutes
- Run-now endpoint fails or doesn't return a run ID
- Concurrency limits are not enforced in schedule configuration
- Any unexpected error occurs

## Troubleshooting

**Scheduler not running:**
```bash
docker-compose up -d scheduler
docker-compose logs -f scheduler
```

**Timeout waiting for runs:**
- Check scheduler logs: `docker-compose logs scheduler`
- Verify database connectivity
- Confirm schedules are enabled: `curl http://localhost:9595/api/schedules/`

**API connection refused:**
- Verify web service is running: `docker-compose ps web`
- Check if port 9595 is accessible: `curl http://localhost:9595/`

## Expected Output

```
============================================================
🧠 Phase 2 Smoke Test: Scheduling
============================================================
🔍 Checking scheduler service status...
  ✅ Scheduler service running
🔧 Setting up test directive...
  ✅ Using existing directive: 1
🔍 Fetching available jobs...
  ✅ Found 3 jobs

📅 Creating schedules for each job...
  ✅ Created schedule: smoke-task1-1234567890 (ID: 1)
  ✅ Created schedule: smoke-task2-1234567890 (ID: 2)
  ✅ Created schedule: smoke-task3-1234567890 (ID: 3)

⏳ Waiting up to 180s for scheduled runs...
  ✅ Schedule 1 has successful run
  ✅ Schedule 2 has successful run
  ✅ Schedule 3 has successful run
  ✅ All schedules completed in 65.2s

🚀 Testing run-now for schedule 1...
  ✅ Run-now created run: 10

🔒 Testing concurrency limits...
  ✅ Created concurrency test schedule: 4
  ✅ Created concurrency test schedule: 5
  ✅ Triggered run: 11
  ✅ Triggered run: 12
  ℹ️  Active runs at check time: 1 (max expected: 1)
  ✅ Concurrency limits configured correctly

🧹 Cleaning up schedules...
  ✅ Schedules disabled

============================================================
✅ PASS: Phase 2 scheduling smoke test complete
============================================================
```
