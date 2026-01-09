`.github/copilot-instructions.md`

# Cyberbrain Orchestrator — Copilot Agent Instructions (ATDD + DbC + CI Gates)

## Primary Development Model (Non-Negotiable)
This repo follows **ATDD + Contracts (DbC) + strong CI gates**.

### Required workflow (in order)
1. **Write/Update an Acceptance Test first (ATDD)** that expresses “done” from an API/user standpoint and fails on current code.
2. Implement the **minimum** code to make the acceptance test pass.
3. Add/adjust **Contracts (DbC)** at boundaries (inputs/outputs, invariants) and add **negative tests** proving contracts fail correctly.
4. Run **all gates** locally before considering work complete.

### Output rules (Copilot)
- Make **small diffs**; avoid sweeping refactors unless explicitly requested.
- Do **not** add new dependencies without stating why and offering a no-new-deps alternative.
- If requirements are ambiguous: add a **failing acceptance test** that captures the ambiguity and ask for the missing requirement.
- Preserve the security guardrails below (especially “no LLM content storage”).

---

## Project Overview
Django 5 orchestration system for managing Docker container tasks with DRF API. Executes task workflows (log triage, GPU reporting, service mapping) using Docker socket integration. Currently in Phase 1 migration from `orchestrator/` app to modular structure.

---

## Architecture
**Dual Model System (Migration in Progress):**
- **Legacy:** `orchestrator/` app with simple models (Directive, Run, Job, LLMCall, ContainerAllowlist)
- **Phase 1:** `core/` app with enhanced models including directive snapshots, RunArtifact, ContainerInventory, WorkerImageAllowlist
- **Coexistence:** Both systems currently active; Phase 1 models in `core/models.py` have proper indexes and guardrails

**Key Apps:**
- `core/` - Enhanced Phase 1 models (security guardrails + indexes)
- `orchestrator/` - Legacy models + DRF API views/serializers
- `api/` - Skeleton for new API (planned)
- `orchestration/` - Worker orchestration (planned)
- `mcp/` - MCP server integration (planned, see `MISSING_FEATURES.md`)

---

## Critical Patterns

### 1. SECURITY GUARDRAIL: No LLM Content Storage
**Never store LLM prompts or responses.** Only store token counts in `LLMCall` model:

```python
# CORRECT: Token counts only
LLMCall.objects.create(
    job=job,
    model_name='gpt-4',
    prompt_tokens=150,
    completion_tokens=300,
    total_tokens=450
)

# WRONG: Never do this
# Never add prompt= or response= fields to any model
```
This guardrail is also enforced by warnings in `core/models.py` and settings. Maintain them.

### 2. Directive Snapshots (Phase 1 Pattern)
Runs store directive **snapshots** (JSON), not foreign keys. This preserves exact configuration even if directive changes later:

```python
# Phase 1 (core/models.py):
class Run(models.Model):
    directive_snapshot = models.JSONField(...)  # Stores entire directive at run time

# Legacy (orchestrator/models.py):
class Run(models.Model):
    directive = models.ForeignKey(Directive, ...)  # Reference (to be migrated)
```

### 3. Task Nomenclature Variance
**Two naming conventions coexist:**
- **Phase 1 (`core/models.py`):** `task1`, `task2`, `task3`
- **Legacy (`orchestrator/models.py`):** `log_triage`, `gpu_report`, `service_map`

When adding code, match the system you're modifying.

### 4. Docker Socket Integration
Container access via `/var/run/docker.sock` mounted in docker-compose. All container operations must check `ContainerAllowlist`:

```python
# In orchestrator/services.py:
def is_container_allowed(self, container_id):
    return ContainerAllowlist.objects.filter(
        container_id=container_id, is_active=True
    ).exists()
```

### 5. Status Tracking Evolution
- **Legacy:** `pending`, `running`, `completed`, `failed`
- **Phase 1:** `pending`, `running`, `success`, `failed`, `partial` (explicit success vs failure)

---

## ATDD (Acceptance Test–Driven Development)

### What qualifies as an acceptance test here
Acceptance tests verify behavior at the DRF API boundary (preferred), e.g.:
- `POST /api/runs/launch/` launches a run with tasks and returns a predictable payload
- retrieving a run reflects correct status changes and job creation
- security constraints are enforced (allowlist, no prompt storage, redaction mode expectations)

### Placement and naming
- Put acceptance tests under: `tests/acceptance/` (create if missing)
- Use descriptive names, e.g. `test_runs_launch_creates_jobs_for_tasks.py`

### Acceptance tests must:
- Assert **observable behavior** (HTTP status, response JSON shape, DB side effects)
- Cover **at least one negative path** (e.g., disallowed container, invalid tasks)
- Be stable (no timing flakiness; mock external calls when needed)

---

## Contracts (Design by Contract / DbC)

### Where to enforce contracts
Add contracts at **boundaries**:
- DRF serializers / view actions (`launch`, etc.)
- service entrypoints in `orchestrator/services.py`
- worker/task execution functions
- model methods that encapsulate invariants

### How to express contracts in this codebase
Prefer **explicit validation + clear exceptions**:
- serializer validation for request payloads
- raising `ValidationError` (DRF) for request issues
- raising domain-specific exceptions for service-layer invariants
- use `assert` sparingly (only for internal invariants that should never fail in production)

### Contract expectations (examples)
- `tasks` must be a non-empty list of known task identifiers for the target system
- docker container operations require allowlist approval
- outputs must never include secret content when `DEBUG_REDACTED_MODE=True`

Every new/changed contract must have:
- at least one **acceptance test** proving behavior from the API boundary
- at least one **unit test** proving the contract rejects bad input

---

## CI Gates (Strong, deterministic, must pass)

### Minimum required gates (run locally and in CI)
1. **Validation script**
   - `python validate.py`
2. **Unit tests**
   - `python manage.py test --settings=cyberbrain_orchestrator.test_settings`
3. **Acceptance tests**
   - Must be executed as part of the test suite (either included in Django test discovery or invoked separately)

### Optional-but-preferred gates (do not add dependencies without approval)
If the repo already has them configured, run them:
- `ruff check .` and/or `ruff format .`
- `pyright` (or `mypy`)
- `python manage.py makemigrations --check --dry-run` (to prevent uncommitted migrations)
- `python -m compileall .`

If these tools are not present, do **not** introduce them automatically. Propose the change with rationale.

---

## Development Workflows

### Running Tests
```bash
# Unit tests (uses SQLite via test_settings.py)
python manage.py test --settings=cyberbrain_orchestrator.test_settings

# Validation script
python validate.py
```

### Docker Compose Setup
```bash
# Start services (PostgreSQL + Django on HOST IP:9595)
docker-compose up -d

# Apply migrations (both apps)
docker-compose exec web python manage.py migrate

# View logs
docker-compose logs -f web
```

Access:
- Web UI: `http://<UNRAID_HOST>:9595/` (replace with Unraid LAN IP or hostname)
- MCP endpoint: `http://<UNRAID_HOST>:9595/mcp`
- API base: `http://<UNRAID_HOST>:9595/api/`

### Creating Migrations
```bash
# For orchestrator (legacy)
python manage.py makemigrations orchestrator

# For core (Phase 1)
python manage.py makemigrations core
```

---

## Environment Variables
Configured via `.env` file (not committed):
- `CYBER_BRAIN_LOGS` - Log directory mount (defaults to `./logs`)
- `UPLOADS_DIR` - File uploads (Phase 1 needs rename to `CYBER_BRAIN_UPLOADS`)
- `DEBUG_REDACTED_MODE` - When `True`, redact sensitive content from logs (default: `True`)
- `POSTGRES_*` - Database credentials
- Network binding: `HOST IP:9595` (generic bind on all interfaces; see docker-compose `ports: ["9595:8000"]`)

---

## API Conventions
**DRF ViewSets with `AllowAny` permissions** (production auth not implemented):

```python
# In orchestrator/views.py:
class RunViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=['post'])
    def launch(self, request):
        # POST /api/runs/launch/ with {'tasks': [...]}
        ...
```

**Serializer nesting:**
- List views use simplified serializers (`RunListSerializer` with `job_count`)
- Detail views use nested serializers (`RunSerializer` includes full `jobs` array)

---

## Key Files to Reference
- `orchestrator/services.py` - Docker integration, task execution (log_triage, gpu_report, service_map)
- `core/models.py` - Phase 1 models with indexes and security comments
- `cyberbrain_orchestrator/settings.py` - Multi-app config, ASGI support (Channels installed but not configured)
- `PHASE1_STATUS.md` - Migration progress, completed vs planned features
- `MISSING_FEATURES.md` - Known gaps (MCP endpoint, ASGI server, app refactor)

---

## What's Not Here Yet
See `MISSING_FEATURES.md` for Phase 1 gaps:
- MCP endpoint at `/mcp` with SSE support (dependency installed, not configured)
- ASGI server (using Gunicorn, should migrate to Uvicorn/Daphne)
- Full app refactor (API split, orchestration workers)
- Enhanced API endpoints (directive snapshots in requests, "since last successful run" queries)

---

## When Editing Models
1. Check if editing legacy (`orchestrator/`) or Phase 1 (`core/`) app
2. For `core/models.py`: Maintain security guardrail comments
3. For new fields: Add appropriate indexes (match existing patterns in `core/models.py`)
4. Never add prompt/response storage fields to any model
5. Run migrations for both apps if schema changes affect relationships

---

## Copilot “Definition of Done”
A change is done only when:
- Acceptance test(s) exist and pass
- Contract validation exists at boundaries and negative tests cover it
- `python validate.py` passes
- `python manage.py test --settings=cyberbrain_orchestrator.test_settings` passes
- No security guardrails are weakened (especially no LLM content storage)