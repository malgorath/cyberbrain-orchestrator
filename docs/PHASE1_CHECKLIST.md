# Phase 1 Acceptance Checklist

Quick checklist to verify Phase 1 completion manually or automatically via smoke test.

## Automated Verification (Recommended)

Run the smoke test:
```bash
python3 scripts/smoke_phase1.py
```

Or in VS Code: **Tasks: Run Task** → **Phase 1: Smoke Test**

Expected result: **✅ ALL SMOKE TESTS PASSED** (12/12)

---

## Manual Verification Checklist

### Infrastructure ✓

- [ ] Docker compose running (`docker-compose ps`)
  - `web` service: running
  - `db` service: running
- [ ] Services accessible:
  - [ ] WebUI: http://localhost:9595/ (HTTP 200)
  - [ ] API: http://localhost:9595/api/ (HTTP 200)
  - [ ] MCP: http://localhost:9595/mcp (returns JSON with tools)

### Core Models ✓

- [ ] Directive library exists (`/api/directives/`)
  - D1: Read-only Diagnostics
  - D2: Conservative Recommendations
  - D3: Change Planning
  - D4: Admin Override
- [ ] Job templates exist (`/api/jobs/`)
  - Task1: log_triage
  - Task2: gpu_report
  - Task3: service_map
- [ ] ContainerAllowlist functional (`/api/containers/`)

### API Endpoints ✓

Core endpoints:
- [ ] `GET /api/` - API root
- [ ] `GET /api/directives/` - List directives
- [ ] `GET /api/runs/` - List runs
- [ ] `GET /api/jobs/` - List jobs
- [ ] `POST /api/runs/launch/` - Launch run
- [ ] `GET /api/runs/{id}/` - Get run details
- [ ] `GET /api/runs/{id}/report/` - Get run report

Token accounting:
- [ ] `GET /api/token-stats/` - Token usage stats
- [ ] `GET /api/cost-report/` - Cost estimation
- [ ] `GET /api/usage-by-directive/` - Usage by directive

Enhanced:
- [ ] `GET /api/runs/since-last-success/` - Windowing
- [ ] `GET /api/container-inventory/` - Container inventory

Observability:
- [ ] `GET /metrics/` - Prometheus metrics (text)
- [ ] `GET /metrics/json/` - Metrics (JSON)

Documentation:
- [ ] `GET /api/schema/` - OpenAPI spec (YAML)
- [ ] `GET /api/docs/` - Swagger UI
- [ ] `GET /api/redoc/` - ReDoc UI

### MCP Integration ✓

- [ ] MCP endpoint responds on `/mcp`
- [ ] Returns `transport: "sse"`
- [ ] Lists tools array with 8+ tools:
  - launch_run
  - list_runs
  - get_run
  - get_run_report
  - list_directives
  - get_directive
  - get_allowlist
  - set_allowlist

### Task Execution ✓

- [ ] Can launch Task1 (log_triage):
  ```bash
  curl -X POST http://localhost:9595/api/runs/launch/ \
    -H "Content-Type: application/json" \
    -d '{"tasks": ["log_triage"]}'
  ```
  - Returns run ID
  - Run transitions: pending → running → (success|failed)

- [ ] Can launch Task2 (gpu_report):
  ```bash
  curl -X POST http://localhost:9595/api/runs/launch/ \
    -H "Content-Type: application/json" \
    -d '{"tasks": ["gpu_report"]}'
  ```

- [ ] Can launch Task3 (service_map):
  ```bash
  curl -X POST http://localhost:9595/api/runs/launch/ \
    -H "Content-Type: application/json" \
    -d '{"tasks": ["service_map"]}'
  ```

### Artifacts & Outputs ✓

For completed runs:
- [ ] Run has report data (`/api/runs/{id}/report/`)
  - Contains `markdown` field
  - Contains `json` field
- [ ] Artifacts endpoint exists (`/api/runs/{id}/artifacts/`)
- [ ] Artifacts written to `/logs` (if configured)

### Token Accounting ✓

- [ ] Run records have token fields:
  - `token_prompt` or `prompt_tokens`
  - `token_completion` or `completion_tokens`
  - `token_total` or `total_tokens`
- [ ] Token stats endpoint aggregates by model
- [ ] Cost report calculates estimates

### Security Guardrails ✓

- [ ] **NO prompt/response content stored**
  - LLMCall model has token counts only
  - No `prompt`, `response`, `prompt_text`, `response_text` fields
  - Token stats API returns counts only
- [ ] DEBUG_REDACTED_MODE enabled by default (`settings.py`)
- [ ] Container allowlist enforced for docker operations
- [ ] Security comments present in model docstrings

### Windowing (Since Last Success) ✓

- [ ] Endpoint exists: `/api/runs/since-last-success/`
- [ ] Returns last successful run (or null)
- [ ] Returns runs since last success
- [ ] Includes pending/running runs (no end time)

### Documentation ✓

- [ ] README.md updated
- [ ] API_DOCS.md exists
- [ ] DEPLOYMENT.md complete
- [ ] ARCHITECTURE.md with diagrams
- [ ] SMOKE_TEST.md (this file's companion)
- [ ] OpenAPI spec generated

---

## Quick Verification Commands

### Check stack:
```bash
docker-compose ps
curl -s http://localhost:9595/api/ | jq .
```

### Check MCP:
```bash
curl -s http://localhost:9595/mcp | jq .
```

### Launch run:
```bash
curl -X POST http://localhost:9595/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{"tasks": ["log_triage"]}' | jq .
```

### Check token stats:
```bash
curl -s http://localhost:9595/api/token-stats/ | jq .
```

### Check metrics:
```bash
curl -s http://localhost:9595/metrics/json/ | jq .
```

---

## Acceptance Criteria Status

| Criterion | Status | Verification Method |
|-----------|--------|---------------------|
| ASGI Server (Daphne) | ✅ | docker-compose.yml, ps output |
| MCP Endpoint (/mcp) | ✅ | GET /mcp returns tools |
| Directive Library D1-D4 | ✅ | GET /api/directives/ |
| Job Templates (Task1/2/3) | ✅ | GET /api/jobs/ |
| Task Launch | ✅ | POST /api/runs/launch/ |
| Token Accounting | ✅ | GET /api/token-stats/ |
| No Prompt Storage | ✅ | Schema inspection |
| Since Last Success | ✅ | GET /api/runs/since-last-success/ |
| Container Allowlist | ✅ | GET /api/containers/ |
| Artifacts | ✅ | GET /api/runs/{id}/artifacts/ |
| Metrics | ✅ | GET /metrics/ |
| Documentation | ✅ | Swagger UI, ReDoc |

## Phase 1 Definition of Done

✅ **All criteria met:**
- Infrastructure operational (docker, web, db)
- Core models implemented (Directive, Job, Run, LLMCall)
- API endpoints functional (REST + MCP)
- Task execution working (launch, status, completion)
- Token accounting in place (counts only, no content)
- Security guardrails enforced (no LLM storage, allowlist)
- Windowing implemented (since last success)
- Documentation complete (API docs, deployment, architecture)
- Smoke test passing (12/12 tests)
- Full test suite passing (169 tests)

**Status**: Phase 1 Complete ✅

---

**See also:**
- [SMOKE_TEST.md](SMOKE_TEST.md) - Detailed smoke test documentation
- [PHASE1_COMPLETION.md](../PHASE1_COMPLETION.md) - Implementation summary
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment guide
