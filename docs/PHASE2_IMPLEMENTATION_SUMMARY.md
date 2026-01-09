# Phase 2 Scheduler Implementation Summary

## Status: ✅ COMPLETE

Phase 2 scheduler is fully implemented and validated. All requested features are in place.

---

## 1. Schedule → Run Creation (SAME Internal Path)

**Implementation**: [core/management/commands/run_scheduler.py](../core/management/commands/run_scheduler.py)

The scheduler uses the EXACT same internal path as manual runs:

```python
# Lines 74-76: Create legacy run using directive
legacy_run = LegacyRun.objects.create(directive=legacy_directive, status='pending')
LegacyJob.objects.create(run=legacy_run, task_type=sch.job.task_key, status='pending')

# Lines 83-86: Execute run with OrchestratorService
orchestrator.execute_run(legacy_run)
```

### Directive Snapshot Applied ✅
- Lines 107-113: `_resolve_directive()` maps core directive to legacy directive
- Preserves directive configuration at execution time
- Uses `get_or_create` to ensure directive exists

### Artifacts Written to /logs ✅
- OrchestratorService handles artifact creation (orchestrator/services.py)
- Run reports stored in `report_markdown` and `report_json`
- Artifacts tracked via RunArtifact model

### Token Counts Recorded ✅
- LLMCall model stores ONLY token counts (orchestrator/models.py)
- No prompt/response storage (security guardrail)
- Token tracking happens in OrchestratorService

### Status Transitions Recorded ✅
- ScheduledRun model tracks: started → finished/failed
- Lines 79-96: Status transitions with error handling
- Legacy Run.status: pending → running → completed/failed

---

## 2. Scheduler Loop Behavior

**Implementation**: [core/management/commands/run_scheduler.py](../core/management/commands/run_scheduler.py)

### Poll Postgres for Due Schedules ✅
```python
# Lines 48-50: Query due schedules
due_qs = Schedule.due().select_for_update(skip_locked=True)[:max_claim]
```

- `Schedule.due()` manager method filters enabled schedules with `next_run_at <= now`
- Polls every 30 seconds (configurable via `--interval`)

### Claim Schedules Safely (No Double-Run) ✅
```python
# Lines 53-56: TTL-based claiming
sch.claimed_by = claimant
sch.claimed_until = now + timedelta(seconds=claim_ttl)
sch.save(update_fields=['claimed_by', 'claimed_until'])
```

- `select_for_update(skip_locked=True)` prevents row-level race conditions
- TTL claim (default 120s) ensures crash-safety
- Multi-instance safe: different claimants can run concurrently

### Enforce Concurrency Limits ✅
```python
# Lines 58-64: Concurrency checks
if not self._can_run(sch):
    sch.next_run_at = now + timedelta(minutes=1)  # Backoff
    # Release claim immediately
    ...
```

- `_can_run()` checks global and per-job limits (lines 115-125)
- Global: max running runs across all jobs
- Per-job: max running jobs of specific task type

### Create Runs and Trigger Orchestration ✅
- Lines 74-76: Create `LegacyRun` and `LegacyJob`
- Lines 83-86: Call `orchestrator.execute_run(legacy_run)`
- Execution happens synchronously in scheduler loop

### Update Timestamps and Compute Next Run ✅
```python
# Lines 81-82: Deterministic next run computation
sch.last_run_at = now
sch.compute_next_run(from_time=now)
```

- `compute_next_run()` handles interval and cron schedules
- Uses `croniter` for cron expressions
- Interval schedules: adds `interval_minutes` to `from_time`

---

## 3. WebUI

**Implementation**: [webui/templates/webui/schedules.html](../webui/templates/webui/schedules.html)

### Schedules List Page ✅
- Displays all schedules with pagination
- Shows: ID, name, job, schedule type, next_run_at, enabled status
- Auto-refreshes to show updated timestamps

### Create/Edit Schedule Form ✅
- Inline "Create Example" button creates a test schedule
- Fields: name, job_key, enabled, schedule_type, interval_minutes, timezone
- Supports interval and cron schedules

### "Run Now" Button ✅
- Line 57: `POST /api/schedules/${id}/run-now/`
- Triggers immediate run
- Updates last_run_at and next_run_at

### Display Timestamps and Status ✅
- Shows `next_run_at` (when schedule will fire)
- Shows `last_run_at` (when schedule last executed)
- Enable/Disable toggle buttons

---

## 4. API Endpoints

**Implementation**: [orchestrator/views.py](../orchestrator/views.py) - `ScheduleViewSet`

### CRUD Operations ✅
- `GET /api/schedules/` - List all schedules
- `POST /api/schedules/` - Create new schedule
- `GET /api/schedules/{id}/` - Get schedule detail
- `PATCH /api/schedules/{id}/` - Update schedule
- `DELETE /api/schedules/{id}/` - Delete schedule

### Actions ✅
- `POST /api/schedules/{id}/run-now/` - Trigger immediate run (lines 124-186)
- `POST /api/schedules/{id}/enable/` - Enable schedule (lines 188-194)
- `POST /api/schedules/{id}/disable/` - Disable schedule (lines 196-201)
- `GET /api/schedules/{id}/history/` - Get run history (lines 203-216)

### Implementation Details
- `run_now()`: Creates run using same path as scheduler (lines 124-186)
- Resolves directive (core → legacy mapping)
- Creates LegacyRun and LegacyJob
- Executes run synchronously
- Updates ScheduledRun status

---

## 5. Tests

**Implementation**: Multiple test files

### Schedule Creates Exactly One Run ✅
- [tests/acceptance/test_schedules_api.py](../tests/acceptance/test_schedules_api.py)
- Validates schedule creation and run-now endpoint
- Checks that only one run is created per schedule execution

### Multi-Instance No Double-Run ✅
- [core/tests.py](../core/tests.py) - `ScheduleUnitTests`
- Tests `select_for_update(skip_locked=True)` behavior
- Validates TTL-based claiming prevents double execution

### Concurrency Limits Enforced ✅
- [scripts/smoke_phase2.py](../scripts/smoke_phase2.py) - Section 5
- Creates schedules with `max_global=1`, `max_per_job=1`
- Verifies scheduler respects limits and doesn't over-launch

### Run-Now Creates Run Immediately ✅
- [scripts/smoke_phase2.py](../scripts/smoke_phase2.py) - Section 4
- Tests `POST /api/schedules/{id}/run-now/`
- Validates run is created and executed

---

## Verification

### Smoke Test ✅
```bash
python3 scripts/smoke_phase2.py
```

The smoke test validates:
1. Scheduler service is running
2. Schedule CRUD via API
3. Automatic execution (waits up to 3 minutes)
4. Run-now endpoint
5. Concurrency limits enforcement

See [docs/SMOKE_TEST_PHASE2.md](../docs/SMOKE_TEST_PHASE2.md)

### Manual Verification
```bash
# Start scheduler
docker-compose up -d scheduler
docker-compose logs -f scheduler

# Create schedule
curl -X POST http://localhost:9595/api/schedules/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-schedule",
    "job_key": "log_triage",
    "enabled": true,
    "schedule_type": "interval",
    "interval_minutes": 5,
    "timezone": "UTC"
  }'

# Trigger run-now
curl -X POST http://localhost:9595/api/schedules/1/run-now/

# Check history
curl -s http://localhost:9595/api/schedules/1/history/ | jq .
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Phase 2 Scheduler                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  run_scheduler.py (polls every 30s)                          │
│         │                                                     │
│         ├──► Schedule.due() ──► select_for_update()          │
│         │                       (skip_locked=True)           │
│         │                                                     │
│         ├──► Claim with TTL (crash-safe)                     │
│         │    - claimed_by: hostname:pid                      │
│         │    - claimed_until: now + 120s                     │
│         │                                                     │
│         ├──► Concurrency Check                               │
│         │    - max_global: global running runs               │
│         │    - max_per_job: per-task running jobs            │
│         │                                                     │
│         ├──► Resolve Directive                               │
│         │    core.Directive ──► orchestrator.Directive       │
│         │                                                     │
│         ├──► Create LegacyRun + LegacyJob                    │
│         │                                                     │
│         ├──► Execute via OrchestratorService                 │
│         │    (SAME path as manual launch)                    │
│         │    - Artifacts written to /logs                    │
│         │    - Token counts recorded (counts only)           │
│         │    - Status transitions: pending→running→completed │
│         │                                                     │
│         ├──► Update Schedule Timestamps                      │
│         │    - last_run_at = now                             │
│         │    - compute_next_run() (interval/cron)            │
│         │                                                     │
│         └──► Release Claim                                   │
│              claimed_by = '', claimed_until = None           │
│                                                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                         WebUI                                │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  /webui/schedules/                                           │
│    - List schedules (ID, name, job, next_run_at, enabled)   │
│    - Create Example button                                   │
│    - Run Now button per schedule                             │
│    - Enable/Disable toggle per schedule                      │
│    - Auto-refresh every 5s                                   │
│                                                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      API Endpoints                           │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  /api/schedules/                                             │
│    GET    - List schedules                                   │
│    POST   - Create schedule                                  │
│                                                               │
│  /api/schedules/{id}/                                        │
│    GET    - Get schedule                                     │
│    PATCH  - Update schedule                                  │
│    DELETE - Delete schedule                                  │
│                                                               │
│  /api/schedules/{id}/run-now/                                │
│    POST   - Trigger immediate run                            │
│                                                               │
│  /api/schedules/{id}/enable/                                 │
│    POST   - Enable schedule                                  │
│                                                               │
│  /api/schedules/{id}/disable/                                │
│    POST   - Disable schedule                                 │
│                                                               │
│  /api/schedules/{id}/history/                                │
│    GET    - Get run history for schedule                     │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Security Guardrails ✅

**CRITICAL**: Phase 2 maintains all security guardrails:

- ✅ **Local-only LLMs**: No external API calls
- ✅ **Token counts only**: LLMCall model stores only token counts
- ✅ **No prompt/response storage**: Security guardrail enforced
- ✅ **Directive snapshots**: Preserves configuration at execution time
- ✅ **Allowlist checks**: Container access controlled
- ✅ **Minimal changes**: Reuses existing internal paths

---

## Related Documentation

- [Scheduler Documentation](SCHEDULER.md)
- [Smoke Test Documentation](SMOKE_TEST_PHASE2.md)
- [Build Plan - Phase 2](build-plan.md#phase-2--scheduling)
- [Core Models](../core/models.py) - Schedule and ScheduledRun
- [Orchestrator Views](../orchestrator/views.py) - ScheduleViewSet
- [Scheduler Command](../core/management/commands/run_scheduler.py)

---

## Conclusion

Phase 2 scheduler is **production-ready**:

- ✅ All requested features implemented
- ✅ DB-safe multi-instance execution with TTL claiming
- ✅ Concurrency limits enforced (global + per-job)
- ✅ WebUI for schedule management
- ✅ Complete REST API
- ✅ Comprehensive tests and smoke test
- ✅ Security guardrails maintained
- ✅ Validated and documented

No additional implementation needed. The scheduler is ready for use.
