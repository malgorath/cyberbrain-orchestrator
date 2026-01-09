# Phase 5: "Cyber-Brain" Agent Runtime (Autonomy MVP)

## Overview

Phase 5 implements autonomous multi-step workflow execution ("Agent Runs"). An agent takes an operator's natural-language goal and a directive, generates a deterministic execution plan, and runs it step-by-step with budget enforcement.

**Key Innovation:** Agent runs chain existing Tasks (1/2/3) as sub-steps, enabling complex workflows while reusing proven infrastructure.

---

## Architecture

### Core Components

#### 1. **Planner/Router** (Local-Only)
**File:** [orchestrator/agent/planner.py](../orchestrator/agent/planner.py)

- **Class:** `PlannerService`
- **Method:** `plan(goal, directive) -> List[Dict]`
- **Mechanism:** Rules-based keyword matching (no external LLM calls)
  - Maps goal keywords to tasks: "log", "error" → Task 1; "gpu", "memory" → Task 2; "service", "port" → Task 3
  - Respects directive constraints: only selects allowed tasks
  - Deterministic: same goal + directive = same plan every time
- **Output:** JSON list of steps with type, task_id, inputs, step_index
- **Validates against:** Directive task_list and approval_required flags

#### 2. **Execution Engine**
**File:** [orchestrator/agent/executor.py](../orchestrator/agent/executor.py)

- **Class:** `AgentExecutor`
- **Method:** `execute(agent_run) -> None`
- **Mechanism:** Step-by-step iteration with budget tracking
  - Launches each task_call step via `RunLauncher` (reuses Task 1/2/3 infrastructure)
  - Tracks token counts from task runs' LLMCall records
  - Implements retry logic: MAX_RETRIES=3 with exponential backoff
- **Stop Conditions (enforced before each step):**
  - `max_steps`: Step index >= max_steps
  - `time_budget`: Elapsed time > time_budget_minutes
  - `token_budget`: tokens_used >= token_budget
  - `approval_gate`: Blocks if directive.approval_required=True and status='pending_approval'
- **Output:** Updates AgentRun.status, AgentStep.status, tokens_used, report fields

#### 3. **Models** (Phase 5 Data Layer)
**File:** [core/models.py](../core/models.py) (lines 1057-1181)

**AgentRun:**
- `operator_goal` - User's goal/prompt
- `directive_snapshot` - Directive config at creation time (for reproducibility)
- `status` - pending, pending_approval, running, completed, failed, cancelled, timeout, expired
- `current_step` - Index of step being executed
- `max_steps`, `time_budget_minutes`, `token_budget` - Budgets
- `tokens_used` - Running total of token counts (from task LLMCall records)
- `report_markdown`, `report_json` - Final outputs (no LLM content)

**AgentStep:**
- `agent_run` - FK to AgentRun
- `step_index` - Position in workflow (0-based)
- `step_type` - task_call, decision, wait, notify
- `task_id` - For task_call steps (log_triage, gpu_report, service_map)
- `inputs` - Configuration (no prompts/responses)
- `outputs_ref` - Path reference only (e.g., "runs/123/report"), no inline content
- `task_run_id` - ID of launched Run for task_call steps
- `status` - pending, running, success, failed, skipped
- `error_message` - Transient failure reasons

**Directive Extensions (Phase 5 fields added):**
- `task_list` - JSONField list of allowed task_ids
- `approval_required` - Boolean: if True, agent waits for human approval
- `max_concurrent_runs` - Int: concurrency limit for scheduled execution

---

## Security Guardrails (Non-Negotiable)

### 1. **No LLM Content Storage**
- Agent steps do NOT have `prompt` or `response` fields
- Only token counts from `LLMCall` records are tracked
- Planner is rules-based (no LLM calls)
- **Enforced by:** Model field definitions + acceptance tests

### 2. **Local-Only Planning**
- Planner uses keyword matching (no cloud API calls)
- Deterministic: same input = same output
- **Alternative:** Could use local sentence-transformers for embeddings (future)

### 3. **Token-Counts-Only Logging**
- `RetrievalEvent` (from Phase 3) stores query_hash, not query_text
- `LLMCall` stores prompt_tokens, completion_tokens, total_tokens (no content)
- **Verified by:** `test_no_llm_content_storage()` acceptance test

### 4. **Directive Snapshots**
- Agent run stores entire directive config at creation time
- Allows reproduction even if directive changes later
- **Implementation:** `Directive.to_json()` → AgentRun.directive_snapshot

---

## API Endpoints

### DRF ViewSet: `AgentRunViewSet`
**File:** [orchestrator/agent_views.py](../orchestrator/agent_views.py)  
**Base:** `/api/agent-runs/`

#### POST `/api/agent-runs/launch/`
**Launch a new agent run.**

**Request:**
```json
{
  "operator_goal": "Analyze system logs and report GPU usage",
  "directive_id": 1,                    // Optional, defaults to first active
  "max_steps": 5,                       // Optional, default 10
  "time_budget_minutes": 10,            // Optional, default 60
  "token_budget": 5000                  // Optional, default 10000
}
```

**Response (201 Created):**
```json
{
  "agent_run_id": 42,
  "status": "pending",
  "plan": [
    {
      "step_index": 0,
      "step_type": "task_call",
      "task_id": "log_triage",
      "inputs": {"goal": "Analyze...", "task_config": {...}}
    },
    {
      "step_index": 1,
      "step_type": "task_call",
      "task_id": "gpu_report",
      "inputs": {...}
    }
  ],
  "created_at": "2026-01-09T01:23:45Z"
}
```

**Validation:**
- operator_goal non-empty
- directive_id exists (if provided)
- budgets within ranges (1-100 steps, 1-1440 minutes, 100-1M tokens)

**Behavior:**
- If `directive.approval_required=True`: status='pending_approval', awaits manual approval
- Otherwise: status='pending', executor runs immediately

---

#### GET `/api/agent-runs/`
**List all agent runs (last 50).**

**Response (200):**
```json
{
  "results": [
    {
      "id": 42,
      "operator_goal": "Analyze system logs and report GPU us...",
      "status": "completed",
      "current_step": 2,
      "tokens_used": 1240,
      "token_budget": 5000,
      "created_at": "2026-01-09T01:23:45Z",
      "started_at": "2026-01-09T01:23:46Z",
      "ended_at": "2026-01-09T01:24:12Z"
    }
  ],
  "count": 1
}
```

---

#### GET `/api/agent-runs/{id}/`
**Get agent run details (including step breakdown).**

**Response (200):**
```json
{
  "id": 42,
  "operator_goal": "Analyze system logs...",
  "status": "completed",
  "current_step": 2,
  "max_steps": 5,
  "time_budget_minutes": 10,
  "token_budget": 5000,
  "tokens_used": 1240,
  "started_at": "2026-01-09T01:23:46Z",
  "ended_at": "2026-01-09T01:24:12Z",
  "steps": [
    {
      "step_index": 0,
      "step_type": "task_call",
      "task_id": "log_triage",
      "status": "success",
      "task_run_id": 123,
      "started_at": "2026-01-09T01:23:46Z",
      "ended_at": "2026-01-09T01:23:52Z",
      "duration_seconds": 6.0,
      "error_message": null
    },
    {
      "step_index": 1,
      "step_type": "task_call",
      "task_id": "gpu_report",
      "status": "success",
      "task_run_id": 124,
      "started_at": "2026-01-09T01:23:52Z",
      "ended_at": "2026-01-09T01:24:12Z",
      "duration_seconds": 20.0,
      "error_message": null
    }
  ],
  "error_message": null
}
```

---

#### POST `/api/agent-runs/{id}/status/`
**Get current status (lightweight).**

**Response (200):**
```json
{
  "agent_run_id": 42,
  "status": "running",
  "current_step": 1,
  "max_steps": 5,
  "tokens_used": 500,
  "token_budget": 5000,
  "time_elapsed_minutes": 1.5,
  "is_expired": false
}
```

---

#### POST `/api/agent-runs/{id}/report/`
**Get final report (markdown + JSON).**

**Response (200):**
```json
{
  "summary": {
    "agent_run_id": 42,
    "operator_goal": "Analyze system logs...",
    "status": "completed",
    "total_steps": 2,
    "successful_steps": 2,
    "failed_steps": 0,
    "tokens_used": 1240,
    "token_budget": 5000,
    "time_elapsed_minutes": 0.44,
    "steps": [...]
  },
  "markdown": "# Agent Run Report 42\n\n**Goal:** Analyze...\n\n**Status:** completed\n\n**Duration:** 0.4 minutes\n\n**Tokens Used:** 1240 / 5000\n\n## Steps\n\n- ✅ Step 0: log_triage (6.0s)\n- ✅ Step 1: gpu_report (20.0s)\n",
  "json": {}
}
```

---

#### POST `/api/agent-runs/{id}/cancel/`
**Cancel an in-progress agent run.**

**Response (200):**
```json
{
  "agent_run_id": 42,
  "status": "cancelled"
}
```

**Constraints:**
- Only valid for status in [pending, pending_approval, running]
- Returns 400 if already completed/failed/cancelled

---

## MCP Tools

**File:** [mcp/views.py](../mcp/views.py) (lines ~290-410)

Four tools for agent operations via MCP protocol:

### 1. `agent_launch`
```json
{
  "tool": "agent_launch",
  "params": {
    "goal": "Analyze system",
    "directive_id": 1,
    "budgets": {
      "max_steps": 5,
      "time_minutes": 10,
      "tokens": 5000
    }
  }
}
```

**Response:** Same as `/api/agent-runs/launch/` (SSE stream)

---

### 2. `agent_status`
```json
{
  "tool": "agent_status",
  "params": {"agent_run_id": 42}
}
```

**Response:** Same as `POST /api/agent-runs/{id}/status/`

---

### 3. `agent_report`
```json
{
  "tool": "agent_report",
  "params": {"agent_run_id": 42}
}
```

**Response:** Includes summary + json (markdown as SSE text)

---

### 4. `agent_cancel`
```json
{
  "tool": "agent_cancel",
  "params": {"agent_run_id": 42}
}
```

**Response:** `{"agent_run_id": 42, "status": "cancelled"}`

---

## Background Executor

### Management Command: `run_agent_executor`
**File:** [core/management/commands/run_agent_executor.py](../core/management/commands/run_agent_executor.py)

Polls for pending agent runs and executes them with crash-safe claiming.

**Usage:**
```bash
# Run with 5s poll interval (default) and 300s TTL (default)
python manage.py run_agent_executor

# Custom interval and TTL
python manage.py run_agent_executor --interval=10 --ttl=600
```

**Features:**
- Polls `AgentRun.objects.filter(status__in=['pending', 'pending_approval'])`
- Skips approval-pending runs until manually approved
- Uses `select_for_update(skip_locked=True)` for concurrency safety
- TTL-based claiming prevents zombie claims if worker crashes
- Automatic retry on transient failures
- Logs all execution events to logger

**Docker Usage:**
```yaml
# docker-compose.yml
agent-executor:
  build: .
  command: python manage.py run_agent_executor --interval=5
  environment:
    - DATABASE_URL=postgresql://...
  depends_on:
    - db
```

---

## WebUI (Optional)

Not implemented in this release. Placeholder for future.

**Planned:**
- Agent Runs list page
- Create new agent run form (goal, directive, budgets)
- Live step execution view
- Report viewer with markdown + JSON

---

## Example Workflow

### 1. Create a directive (if needed)
```bash
curl -X POST http://localhost:9595/api/directives/ \
  -H "Content-Type: application/json" \
  -d '{
    "directive_type": "D4",
    "name": "analysis_directive",
    "task_list": ["log_triage", "gpu_report"],
    "approval_required": false,
    "max_concurrent_runs": 5
  }'
```

### 2. Launch agent run
```bash
curl -X POST http://localhost:9595/api/agent-runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{
    "operator_goal": "Check system health: analyze logs and report GPU",
    "directive_id": 1,
    "max_steps": 5,
    "time_budget_minutes": 10,
    "token_budget": 5000
  }'
# Response: {"agent_run_id": 42, "status": "pending", "plan": [...]}
```

### 3. Monitor execution
```bash
# Check status
curl -X POST http://localhost:9595/api/agent-runs/42/status/
# Response: {"status": "running", "current_step": 1, ...}

# Get report once complete
curl -X POST http://localhost:9595/api/agent-runs/42/report/
# Response: {"summary": {...}, "markdown": "...", "json": {...}}
```

---

## Testing

### Acceptance Tests
**File:** [tests/acceptance/test_agent_runs.py](../tests/acceptance/test_agent_runs.py)

**Coverage:**
- Planner produces valid deterministic plans
- Engine executes 2-step plans
- Budget enforcement (max_steps, time, tokens)
- Approval gating blocks execution
- No LLM content storage
- MCP tools work correctly

**Run:**
```bash
python manage.py test tests.acceptance.test_agent_runs --settings=cyberbrain_orchestrator.test_settings -v 2
```

**Result:** 17 tests, all passing ✅

### Smoke Test
**File:** [scripts/smoke_phase5.py](../scripts/smoke_phase5.py)

**Coverage:**
1. Service health check
2. Create test directive
3. Agent launch with plan
4. Plan structure validation
5. Agent status endpoint
6. Max steps budget
7. Token budget
8. Time budget
9. Approval gating
10. No LLM content
11. Report generation

**Run:**
```bash
# Direct
python3 scripts/smoke_phase5.py

# Via curl (if services running)
# Tests require http://localhost:9595/api/ accessible
```

---

## Database Migrations

**Migration:** [core/migrations/0008_directive_approval_required_and_more.py](../core/migrations/0008_directive_approval_required_and_more.py)

**Changes:**
- Adds Directive fields: task_list, approval_required, max_concurrent_runs
- Creates AgentRun table
- Creates AgentStep table
- Indexes for status, step_index, timestamps

**Run:**
```bash
python manage.py migrate
```

---

## Constraints & Limitations

### Phase 5 MVP Scope
- ✅ Reuses existing Task 1/2/3 infrastructure
- ✅ Local-only planning (no cloud LLM)
- ✅ Token counts only (no content storage)
- ✅ Single-sequential execution (no parallel steps)
- ❌ No parallel task execution (V2 feature)
- ❌ No dynamic branching (V2 feature)
- ❌ No persistent MCP session context (V2 feature)

### Known Limitations
- **Wait steps not implemented:** Can add delay but no actual functionality
- **Decision steps not implemented:** Placeholder for future conditional logic
- **Notify steps not implemented:** Placeholder for future notifications
- **Manual approval not integrated to WebUI:** Approval status requires API call to change

---

## File Manifest

| File | Lines | Purpose |
|------|-------|---------|
| [core/models.py](../core/models.py) | 1057-1181 | AgentRun, AgentStep models; Directive extensions |
| [orchestrator/agent/planner.py](../orchestrator/agent/planner.py) | 125 | PlannerService for plan generation |
| [orchestrator/agent/executor.py](../orchestrator/agent/executor.py) | 210 | AgentExecutor for step-by-step execution |
| [orchestrator/agent_views.py](../orchestrator/agent_views.py) | 360 | DRF API endpoints |
| [orchestrator/agent/__init__.py](../orchestrator/agent/__init__.py) | 1 | Module init |
| [orchestrator/urls.py](../orchestrator/urls.py) | 20 | Route registration |
| [mcp/views.py](../mcp/views.py) | 120 (agent tools) | MCP tool implementations |
| [core/management/commands/run_agent_executor.py](../core/management/commands/run_agent_executor.py) | 65 | Background executor loop |
| [tests/acceptance/test_agent_runs.py](../tests/acceptance/test_agent_runs.py) | 460 | 17 acceptance tests |
| [scripts/smoke_phase5.py](../scripts/smoke_phase5.py) | 350 | End-to-end smoke test |
| [core/migrations/0008_*.py](../core/migrations/0008_directive_approval_required_and_more.py) | 30 | Database migrations |

---

## Deployment Checklist

- [ ] Run migrations: `python manage.py migrate`
- [ ] Run validation: `python validate.py`
- [ ] Run tests: `python manage.py test tests.acceptance.test_agent_runs --settings=cyberbrain_orchestrator.test_settings`
- [ ] Start executor: `python manage.py run_agent_executor` (background)
- [ ] Test API: `curl http://localhost:9595/api/agent-runs/launch/`
- [ ] Test MCP: Send `agent_launch` tool to MCP endpoint
- [ ] Verify in DB: `select * from core_agentrun;`

---

## Summary

**Phase 5 achieves:**
- ✅ Autonomous multi-step workflows via agent runs
- ✅ Local-only planning (rules-based keyword matching)
- ✅ Budget enforcement (steps, time, tokens)
- ✅ Approval gating for sensitive directives
- ✅ Complete REST API + MCP tools
- ✅ Crash-safe background executor
- ✅ Comprehensive testing (17 acceptance tests + smoke test)
- ✅ Security guardrails (no LLM content storage)
- ✅ Minimal changes (reuses Tasks 1/2/3 infrastructure)

**Definition of Done:**
- All acceptance tests passing ✅
- Smoke test validates end-to-end ✅
- Django check identifies no issues ✅
- validate.py passes ✅
- No security guardrails weakened ✅
