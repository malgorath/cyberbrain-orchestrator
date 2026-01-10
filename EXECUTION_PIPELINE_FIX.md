# Execution Pipeline Fix - Verification Guide

## What Was Fixed

The execution pipeline was broken: runs/jobs created via `/api/runs/launch/` would stay `pending` forever because the scheduler had nothing to process. This has been fixed by connecting the launch API to the scheduler via the Schedule model.

## Architecture Changes

### Before (Broken)
```
POST /api/runs/launch/
  ↓
Create Run + Jobs
  ↓
Return 201 (Run stays pending forever)
```

Scheduler ran but had no schedules to process.

### After (Fixed)
```
POST /api/runs/launch/
  ↓
Create Run + Jobs + Schedules + ScheduledRun links
  ↓
Return 201
  ↓
Scheduler claims schedules (next_run_at = now)
  ↓
Executes existing Run (not create new one)
  ↓
Jobs: pending → running → completed/failed
  ↓
Run: pending → running → completed/failed
```

## Implementation Details

### 1. Launch API (`orchestrator/views.py`)
After creating Run + Jobs, now also:
- Gets/creates `core.Job` template for each task type
- Creates `Schedule` with `next_run_at=now()` (due immediately)
- Creates `ScheduledRun` linking Schedule → Run with status='pending'

```python
# For each task in ['log_triage', 'gpu_report', 'service_map']:
schedule = Schedule.objects.create(
    name=f'launch-run-{run.id}-{task_type}',
    job=core_job,
    schedule_type='interval',
    interval_minutes=999999,  # Effectively one-time
    next_run_at=timezone.now(),  # Due immediately
    enabled=True
)

ScheduledRun.objects.create(
    schedule=schedule,
    run=run,
    status='pending'
)
```

### 2. Scheduler (`core/management/commands/run_scheduler.py`)
Enhanced to detect launched runs:

```python
# Check if schedule has existing ScheduledRun from launch
existing_scheduled_run = ScheduledRun.objects.filter(
    schedule=sch,
    status='pending'
).select_related('run').first()

if existing_scheduled_run:
    # Launched run: use existing run
    legacy_run = existing_scheduled_run.run
    existing_scheduled_run.status = 'started'
else:
    # Recurring schedule: create new run (existing behavior)
    legacy_run = LegacyRun.objects.create(...)

# Execute the run
orchestrator.execute_run(legacy_run)
```

### 3. Acceptance Tests (`tests/acceptance/test_execution_pipeline.py`)
Six tests covering:
- Schedule creation on launch
- Scheduler execution of launched runs
- Job state transitions
- Run status aggregation
- Concurrency limit enforcement
- End-to-end pipeline

## Verification Steps

### 1. Pull Updated Image
```bash
# Wait for GitHub Actions to build (check https://github.com/malgorath/cyberbrain-orchestrator/actions)
docker pull ghcr.io/malgorath/cyberbrain-orchestrator:latest
docker-compose down && docker-compose up -d
```

### 2. Check Scheduler Logs
```bash
# Scheduler should show:
docker-compose logs -f scheduler

# Expected output:
# Scheduler starting (interval=30s)...
# No due schedules found  (initially)
```

### 3. Launch a Run
```bash
# Replace with your host IP/hostname
HOST="localhost:9595"

# Get or create directive
curl -X POST http://${HOST}/api/directives/ \
  -H "Content-Type: application/json" \
  -d '{"name":"test-launch","description":"Test execution pipeline"}'

# Launch run with 1 task
curl -X POST http://${HOST}/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{"directive_id":1,"tasks":["log_triage"]}' | jq .

# Note the "id" from response
```

### 4. Verify Schedule Creation
```bash
RUN_ID=<id from launch response>

# Check schedules (should show 1 schedule)
curl http://${HOST}/api/schedules/ | jq '.results[] | select(.name | startswith("launch-run-'${RUN_ID}'"))'

# Expected output:
# {
#   "id": 1,
#   "name": "launch-run-1-log_triage",
#   "enabled": true,
#   "schedule_type": "interval",
#   "next_run_at": "2024-01-15T10:30:00Z",  # ~now
#   ...
# }
```

### 5. Watch Execution (Scheduler Tick)
```bash
# Scheduler logs (should claim and execute within 30s)
docker-compose logs -f scheduler

# Expected output:
# Claimed 1 due schedule(s): ['launch-run-1-log_triage']
# Schedule 1 (launch-run-1-log_triage) has existing run 1, executing...
# Starting run 1
# Starting job 1 - log_triage
# Job 1 finished with status: completed
# Run 1 finished with status: completed
```

### 6. Verify Run Completion
```bash
# Check run status (should be 'completed')
curl http://${HOST}/api/runs/${RUN_ID}/ | jq '.status'

# Check job status (should be 'completed')
curl http://${HOST}/api/jobs/?run=${RUN_ID} | jq '.[].status'

# Check ScheduledRun status (should be 'finished')
curl http://${HOST}/api/scheduled-runs/?run=${RUN_ID} | jq '.[].status'
```

## Troubleshooting

### Run Stays Pending
```bash
# Check if schedules were created
curl http://${HOST}/api/schedules/ | jq '.results[] | select(.name | contains("launch-run"))'

# Check scheduler is running
docker-compose ps scheduler

# Check scheduler logs for errors
docker-compose logs scheduler | grep -i error

# Check if schedules are due
curl http://${HOST}/api/schedules/ | jq '.results[] | {name, next_run_at, enabled}'
```

### Scheduler Not Claiming Schedules
```bash
# Check Schedule.due() query (should return schedules with next_run_at <= now)
# Check if schedules are claimed by another instance:
curl http://${HOST}/api/schedules/ | jq '.results[] | {name, claimed_by, claimed_until}'

# If claimed_until is in past, scheduler will claim it on next tick
```

### Jobs Fail Immediately
```bash
# Check job error messages
curl http://${HOST}/api/jobs/?run=${RUN_ID} | jq '.[].error_message'

# Check Docker socket access
docker-compose exec web ls -l /var/run/docker.sock

# Check container allowlist (if using log_triage/service_map)
curl http://${HOST}/api/container-allowlist/
```

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/runs/launch/` | Create run + schedules |
| `GET /api/runs/{id}/` | Get run status |
| `GET /api/jobs/?run={id}` | Get jobs for run |
| `GET /api/schedules/` | List schedules |
| `GET /api/scheduled-runs/?run={id}` | Get schedule execution history |

## Next Steps

Once verified working:
1. Monitor scheduler performance (claim rate, execution time)
2. Adjust `--interval` if needed (default 30s)
3. Consider adding metrics/telemetry for schedule processing
4. Add worker container spawning (currently uses OrchestratorService directly)

## Rollback

If issues occur:
```bash
# Revert to previous commit
git revert 4b3e2b1
git push origin main

# Or use previous image
docker-compose down
docker pull ghcr.io/malgorath/cyberbrain-orchestrator:main-5211e5c
docker-compose up -d
```

## Related Documentation

- [API_DOCS.md](API_DOCS.md) - API reference
- [PHASE1_STATUS.md](PHASE1_STATUS.md) - Phase 1 features
- [WORKERHOST_RUNBOOK.md](docs/WORKERHOST_RUNBOOK.md) - Multi-host operations
- Commit: `4b3e2b1` - "Connect run launch to scheduler execution pipeline"
