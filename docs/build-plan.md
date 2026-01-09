# Cyberbrain Orchestrator — Build Plan

## Phase 1 — Status

- **Completed**
- Validated via acceptance tests and smoke test
- Guardrails enforced: local-only LLMs, tokens-only (no prompt/response content), directive snapshots, allowlist checks
- ASGI server with Channels/Daphne; MCP endpoint available at `/mcp`
- Docker Compose binds HOST IP: `9595:8000` (no fixed LAN IP)

References:
- Phase 1 Checklist: docs/PHASE1_CHECKLIST.md
- Smoke Test: scripts/smoke_phase1.py and docs/SMOKE_TEST.md

---

## Phase 2 — Scheduling

- **Status**: Completed
- Postgres-backed scheduler with DB-safe claiming (TTL + multi-instance correctness)
- CRUD API + Run Now + concurrency limits (global + per-job)
- WebUI for schedule management
- Docker Compose scheduler service
- Validated via acceptance tests and smoke test

References:
- Documentation: docs/SCHEDULER.md
- Smoke Test: scripts/smoke_phase2.py and docs/SMOKE_TEST_PHASE2.md

### Definition of Done

A change is done only when ALL of the following are true:

- Schedules CRUD API exists and works:
  - `GET/POST /api/schedules/`
  - `GET/PATCH/DELETE /api/schedules/{id}/`
  - Actions: `POST /api/schedules/{id}/run-now`, `POST /api/schedules/{id}/enable`, `POST /api/schedules/{id}/disable`
  - Responses include: `enabled`, `next_run_at`, `last_run_at`, `job` and directive summary

- Scheduler service runs in Docker (separate container) and automatically triggers due schedules:
  - Polls Postgres every 10–30 seconds
  - Claims due schedules with DB-safe locking (`select_for_update(skip_locked)`) to avoid double execution
  - Enforces concurrency limits: global max concurrent runs, per-job max concurrent runs
  - Launches runs using the SAME internal path as manual launches (same directives, artifacts, token accounting)
  - Updates `last_run_at` and computes `next_run_at` deterministically (interval + cron)

- Data model present with migrations applied:
  - `Schedule`
    - `name`
    - `job` (FK; by `task_key`)
    - `directive` (nullable) OR `custom_directive_text` (nullable)
    - `enabled` (bool)
    - `schedule_type`: `interval` | `cron`
    - `interval_minutes` (nullable)
    - `cron_expr` (nullable)
    - `timezone`
    - `task3_scope`: `allowlist` | `all`
    - `max_global` (sensible default)
    - `max_per_job` (sensible default)
    - `last_run_at`, `next_run_at`
    - `created_at`, `updated_at`
  - `ScheduledRun` (recommended)
    - `schedule` FK, `run` FK
    - `status`, `started_at`, `finished_at`, `error_summary`
    - NO LLM content stored

- WebUI:
  - Schedules list page shows: `enabled`, `next_run_at`, `last_run_at`, `job`
  - Create/edit form fields: job, directive select or custom text, interval/cron, timezone, scope, concurrency
  - “Run now” button works and reflects in history

- Tests pass:
  - Due schedule creates exactly one Run
  - Disabled schedule does not run
  - Concurrency limits enforced (global + per-job)
  - `next_run_at` correct for interval + cron
  - Regression: manual run launching still works

- Guardrails preserved:
  - Local-only LLMs
  - Tokens-only (no prompt/response storage)
  - Minimal changes to legacy/manual paths

## Running & Validation

- Start stack and scheduler:
```bash
docker-compose up -d
docker-compose up -d scheduler
docker-compose logs -f scheduler
```

- Create a schedule (example — triage every 5m):
```bash
curl -X POST http://<UNRAID_HOST>:9595/api/schedules/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "triage-every-5",
    "job_key": "log_triage",
    "enabled": true,
    "schedule_type": "interval",
    "interval_minutes": 5,
    "timezone": "UTC"
  }'
```

- Trigger immediately:
```bash
curl -X POST http://<UNRAID_HOST>:9595/api/schedules/1/run-now
```

- Check schedule history:
```bash
curl -s http://<UNRAID_HOST>:9595/api/schedules/1/history | jq .
```

- Verify runs and reports:
```bash
curl -s http://<UNRAID_HOST>:9595/api/runs/ | jq .
curl -s http://<UNRAID_HOST>:9595/api/runs/<run_id>/report/ | jq .
```

- WebUI:
  - Schedules page: http://<UNRAID_HOST>:9595/webui/schedules
  - Dashboard button: “Open Schedules”

- **Phase 2 smoke test** (automated validation):
```bash
# Local host (requires venv)
python3 scripts/smoke_phase2.py

# VS Code task: "Phase 2: Smoke Test"

# In container
docker-compose exec -T web /opt/venv/bin/python /app/scripts/smoke_phase2.py
```

The smoke test validates:
1. Scheduler service is running
2. Schedule CRUD via API
3. Automatic execution (waits up to 3 minutes for successful runs)
4. Run-now endpoint functionality
5. Concurrency limits enforcement (max_global=1, max_per_job=1)

See [docs/SMOKE_TEST_PHASE2.md](SMOKE_TEST_PHASE2.md) for detailed PASS/FAIL criteria.

---

## Phase 3 — RAG (Retrieval-Augmented Generation)

- **Status**: Complete
- Local-only RAG with sentence-transformers embeddings
- Upload → ingest → search pipeline with WebUI
- use_rag flag for task integration
- MCP tools for RAG operations
- pgvector integration for efficient similarity search
- Security guardrails: query text HASHED only, no raw storage
- Docker Compose ingester service
- Validated via acceptance tests and smoke test

### Completed Features

**Database & Models** (core/models.py):
- UploadFile: tracks files and ingestion status (queued→processing→ready/failed)
- Document, Chunk, Embedding: document processing and vectors
- RetrievalEvent: logs queries by HASH only (no raw text)
- pgvector integration via migration 0007 (Postgres only, safely skips on SQLite)

**Ingestion Pipeline** (run_ingester):
- Background worker processes queued uploads
- Text extraction: txt, md, json, pdf, docx
- Chunking: 500 words with 50-word overlap
- Local embeddings: sentence-transformers/all-MiniLM-L6-v2
- pgvector storage for efficient similarity search

**API Endpoints** (orchestrator/rag_views.py):
- POST /api/rag/upload - Upload files
- GET /api/rag/uploads - List uploads and status
- POST /api/rag/search - Search chunks (cosine similarity)
- GET /api/rag/documents - List documents

**WebUI** (webui/templates/webui/):
- rag_upload.html: file upload with status tracking and auto-refresh
- rag_search.html: query input with scored results display
- Navigation links between schedules, upload, and search pages

**Task Integration** (orchestrator/services.py):
- Run.use_rag field triggers RAG retrieval before LLM calls
- perform_rag_retrieval() method performs semantic search
- execute_log_triage() enhanced with RAG context when use_rag=true
- RAG usage tracked in job results (rag_used, rag_chunks_retrieved)

**MCP Tools** (mcp/views.py):
- rag_search: semantic search with query hashing (no plaintext storage)
- rag_list_documents: list ingested documents with metadata
- rag_upload_status: check upload processing status and counts

**Docker Compose**:
- ingester service runs run_ingester command with 10s polling

**Tests**:
- tests/acceptance/test_rag.py: Upload → ingest → search acceptance test
- Verifies query text is hashed, NOT stored
- Validates no LLM content persisted
- scripts/smoke_phase3.py: End-to-end smoke test with MCP validation
- docs/SMOKE_TEST_PHASE3.md: Comprehensive test documentation

### References

- Documentation: [docs/PHASE3_RAG.md](PHASE3_RAG.md)
- Smoke Test: [scripts/smoke_phase3.py](../scripts/smoke_phase3.py) and [docs/SMOKE_TEST_PHASE3.md](SMOKE_TEST_PHASE3.md)
- Models: [core/models.py](../core/models.py) (Phase 3 section)
- API: [orchestrator/rag_views.py](../orchestrator/rag_views.py)
- Ingester: [core/management/commands/run_ingester.py](../core/management/commands/run_ingester.py)
- WebUI: [webui/templates/webui/rag_upload.html](../webui/templates/webui/rag_upload.html), [webui/templates/webui/rag_search.html](../webui/templates/webui/rag_search.html)
- Tests: [tests/acceptance/test_rag.py](../tests/acceptance/test_rag.py)

### Security Guardrails

**CRITICAL**: Phase 3 maintains all existing guardrails:
- Local-only embedding models (no external API calls)
- Query text is SHA256 hashed, never stored in plaintext
- RetrievalEvent model has NO query_text field
- Token counts only for LLM calls (no prompt/response storage)
- All RAG operations are privacy-preserving by design

### Running & Validation

Start services with ingester:
```bash
docker-compose up -d
docker-compose up -d ingester

# Or run ingester locally
python manage.py run_ingester
```

Run smoke test:
```bash
python3 scripts/smoke_phase3.py

# VS Code task: "Phase 3: Smoke Test"

# In container
docker-compose exec -T web /opt/venv/bin/python /app/scripts/smoke_phase3.py
```

The smoke test validates:
1. File upload via RAG API
2. Ingestion completion (queued → ready)
3. RAG search returns results
4. MCP RAG search endpoint
5. Run launch with use_rag=true
6. Run completion with report
7. LLM call guardrails (no prompt/response storage)
8. Query privacy (SHA256 hashing only)
9. MCP launch with use_rag=true

See [docs/SMOKE_TEST_PHASE3.md](SMOKE_TEST_PHASE3.md) for detailed PASS/FAIL criteria.

Access WebUI:
- Upload: http://localhost:9595/webui/rag/upload/
- Search: http://localhost:9595/webui/rag/search/

---
- Local-only embedding models (no external API calls)
- Query text is SHA256 hashed, never stored in plaintext
- RetrievalEvent model has NO query_text field
- Token counts only for LLM calls (no prompt/response storage)
- All RAG operations are privacy-preserving by design

---

## Phase 4 — Autonomy + Notifications + Auth

- **Status**: Core Infrastructure Complete
- Notifications for run completion (Discord, email)
- Approval gating for D3/D4 directives
- Network policy recommendations (metadata)
- Auth framework defined (implementation deferred)

### Completed Features

**Notification System** (core/notifications.py):
- NotificationTarget model: Discord webhooks, email
- RunNotification model: tracks delivery status
- Counts-only payloads (no LLM content)
- Test notification endpoint

**Approval Gating** (orchestrator/models.py):
- Run.approval_status field: none|pending|approved|denied
- approved_by and approved_at tracking
- D3/D4 directives marked for approval workflow

**Network Policy Recommendations** (core/models.py):
- NetworkPolicyRecommendation model
- Stores K8s NetworkPolicy YAML
- Links to Run for audit trail

**Tests** (tests/acceptance/test_phase4.py):
- Notification creation on run completion
- Counts-only payload validation
- Approval workflow
- Network policy storage
- Guardrail compliance checks

### Pending Features (Future)

- WebUI for notification management
- WebUI for approval workflow (approve/deny UI)
- MCP tool enforcement of approval status
- AUTH_ENABLED environment flag implementation
- Task 3 integration for automatic policy generation
- Email/Discord configuration in settings

### References

- Documentation: [docs/PHASE4.md](PHASE4.md)
- Notification Service: [core/notifications.py](../core/notifications.py)
- Models: [core/models.py](../core/models.py) (Phase 4 section)
- Tests: [tests/acceptance/test_phase4.py](../tests/acceptance/test_phase4.py)

### Security Guardrails

**CRITICAL**: Phase 4 maintains all existing guardrails:
- Local-only LLMs (no external API calls)
- Token counts only for LLM calls (no prompt/response storage)
- Notification payloads are counts-only (jobs, tokens, status)
- RunNotification model has NO fields for LLM content
- Approval workflow preserves token-only logging


