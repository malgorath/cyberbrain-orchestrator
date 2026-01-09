# Phase 2 Scheduler — Scheduling + Concurrency

Adds Postgres-backed scheduling with concurrency controls. Jobs run automatically via a dedicated scheduler service (Docker), while preserving Phase 1 guardrails.

## Features
- Interval or cron-based schedules
- Concurrency limits: global and per job
- Idempotent schedule claiming via Postgres row locks (`select_for_update(skip_locked)`) to avoid double-runs
- Safe restarts: due schedules are re-claimed and processed
- Actions: run-now, enable, disable, history

## Data Model (core)
- `Schedule`:
  - `name` (unique)
  - `job` (core `Job` FK)
  - `directive` (core `Directive` FK) or `custom_directive_text`
  - `enabled`
  - `schedule_type`: `interval` or `cron`
  - `interval_minutes` or `cron_expr` (e.g., `0 2 * * *`)
  - `timezone` (default `UTC`)
  - `task3_scope`: `allowlist` or `all`
  - `max_global`, `max_per_job` (optional)
  - `last_run_at`, `next_run_at`
- `ScheduledRun`:
  - `schedule` (FK)
  - `run` (legacy `orchestrator.Run` FK)
  - `status`, `started_at`, `finished_at`, `error_summary`

## API Endpoints
- CRUD: `GET/POST /api/schedules/`, `GET/PATCH/DELETE /api/schedules/{id}/`
- Actions:
  - `POST /api/schedules/{id}/run-now`
  - `POST /api/schedules/{id}/enable`
  - `POST /api/schedules/{id}/disable`
  - `GET /api/schedules/{id}/history`

## Scheduler Service
A dedicated container runs the scheduler loop:
- Polls due schedules (`enabled` and `next_run_at <= now`)
- Enforces concurrency limits
- Creates a legacy `Run` and a matching `Job` (same path as manual launches)
- Executes the run via `OrchestratorService`
- Updates `last_run_at` and `next_run_at` deterministically

### docker-compose
A `scheduler` service is added:
```
scheduler:
  build: .
  command: >
    sh -c "/opt/venv/bin/python manage.py migrate &&
           /opt/venv/bin/python manage.py run_scheduler --interval=30"
  volumes:
    - .:/app
    - ${CYBER_BRAIN_LOGS:-./logs}:/logs
    - ${UPLOADS_DIR:-./uploads}:/uploads
    - /var/run/docker.sock:/var/run/docker.sock
  environment:
    - POSTGRES_* (matches web)
  depends_on:
    db:
      condition: service_healthy
    web:
      condition: service_started
  restart: unless-stopped
```

## Usage
- Create a schedule:
```
curl -X POST http://localhost:9595/api/schedules/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "triage-every-10",
    "job_key": "log_triage",
    "enabled": true,
    "schedule_type": "interval",
    "interval_minutes": 10,
    "timezone": "UTC"
  }'
```
- Run now:
```
curl -X POST http://localhost:9595/api/schedules/1/run-now
```
- Enable/Disable:
```
curl -X POST http://localhost:9595/api/schedules/1/enable
curl -X POST http://localhost:9595/api/schedules/1/disable
```
- History:
```
curl -s http://localhost:9595/api/schedules/1/history | jq .
```

## Tests
- TTL-based claiming (`claimed_until`, `claimed_by`) ensures crash-safety and multi-instance correctness; claims auto-expire and are released after scheduling

## Smoke Test (Phase 2)
Run: `python3 scripts/smoke_phase2.py`
- Creates a schedule
- Triggers `run-now`
- Verifies history has an entry
         /opt/venv/bin/python manage.py run_scheduler --interval=30"
## Guardrails
- No LLM prompt/response storage (counts only)
- Local-only LLM endpoints
- `--claim-ttl`: Seconds to hold a schedule claim for crash-safety (default: 120)
- `--claimant`: Identifier for this scheduler instance (defaults to `hostname:pid`)
- Per-task workers remain ephemeral
- Double-runs on restart: verify `claimed_until` is set appropriately; TTL ensures expired claims are reclaimed by active schedulers
## Troubleshooting
- `next_run_at` is empty for cron: ensure `croniter` is installed in the app environment
- Multiple runs per tick: check DB connectivity and confirm scheduler container is single instance, or rely on Postgres `skip_locked`
- Concurrency not enforced: verify `max_global`/`max_per_job` configured and that `orchestrator.Run`/`Job` statuses reflect running correctly
