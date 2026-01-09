# Cyberbrain Orchestrator - Architectural Decisions

This document captures the **non-negotiable architectural constraints** and design decisions for the Cyberbrain Orchestrator project. These are foundational choices that define the system's security posture, deployment model, and operational characteristics.

## Core Security Constraints

### 1. Local-Only LLMs
**Decision:** All LLM interactions must use locally-hosted models. No external API calls to OpenAI, Anthropic, or other cloud providers.

**Rationale:**
- Data sovereignty and privacy requirements
- No sensitive data leaves the local network
- Predictable costs (no per-token API charges)
- Continued operation without internet connectivity

**Implementation Impact:**
- LLM inference happens in Docker containers spawned by the orchestrator
- Worker images must include model weights or mount them from shared storage
- Network isolation for worker containers (no external network access)

### 2. Token Counts Only (No Prompt Storage)
**Decision:** The system MUST NOT store LLM prompts or responses in the database. Only token counts are persisted.

**Rationale:**
- Privacy by design - no LLM content retention
- Prevents accidental logging of sensitive data
- Reduces database bloat from large text fields
- Enables cost tracking without privacy risks

**Implementation:**
```python
# CORRECT: Only store token counts
LLMCall.objects.create(
    job=job,
    model_name='llama-3-70b',
    prompt_tokens=1250,
    completion_tokens=800,
    total_tokens=2050
)

# FORBIDDEN: Never add these fields
# prompt = models.TextField()  # NEVER
# response = models.TextField()  # NEVER
```

**Enforcement:**
- Security warnings in `core/models.py` and `orchestrator/models.py`
- Code review requirement for any model changes
- `DEBUG_REDACTED_MODE` setting to redact content in logs

### 3. Optional PII/SPII-Redacted Debug Mode
**Decision:** System must support `DEBUG_REDACTED_MODE` that redacts Personally Identifiable Information (PII) and Sensitive Personal Information (SPII) from logs and debug output.

**Configuration:**
- Environment variable: `DEBUG_REDACTED_MODE=True` (default: enabled)
- When enabled: Sanitize logs before writing, mask container IDs, redact file paths containing usernames
- When disabled: Full verbose logging for deep debugging (use only in isolated dev environments)

**Rationale:**
- Compliance with privacy regulations (GDPR, CCPA, etc.)
- Safe debugging in production-like environments
- Prevents accidental exposure of sensitive data in log aggregation systems

## Technology Stack (Non-Negotiable)

### 4. Django 5 + Django REST Framework + WebUI
**Decision:** Use Django 5.x as the web framework with DRF for API and built-in WebUI for visualization.

**Components:**
- **Django 5.1.14+** - Core web framework (security updates required)
- **Django REST Framework 3.15+** - RESTful API layer
- **Built-in WebUI** - Simple HTML/CSS/JS dashboard (no React/Vue overhead)

**Rationale:**
- Mature, secure, well-documented framework
- Built-in admin interface for operational management
- Strong ORM for PostgreSQL integration
- DRF provides standardized API conventions
- Minimal frontend complexity (no Node.js build pipeline)

### 5. ASGI Server for Async Support
**Decision:** Deploy with ASGI server (Uvicorn/Daphne) for async request handling and SSE support.

**Current State:**
- ⚠️ Using Gunicorn (WSGI) in docker-compose - **needs migration**
- Dependencies installed: `uvicorn[standard]==0.34.0`, `daphne==4.1.2`, `channels==4.2.0`

**Required Change:**
```yaml
# docker-compose.yml - MUST UPDATE
command: >
  sh -c "python manage.py migrate &&
         python manage.py collectstatic --noinput &&
         daphne cyberbrain_orchestrator.asgi:application -b 0.0.0.0 -p 8000"
```

**Rationale:**
- SSE (Server-Sent Events) requires long-lived connections
- MCP endpoint needs streaming responses
- Async task monitoring and real-time updates
- Future WebSocket support for live job status

### 6. MCP Endpoint at `/mcp` (Streamable HTTP + SSE)
**Decision:** Model Context Protocol (MCP) server exposed at `/mcp` using Streamable HTTP transport with Server-Sent Events.

**Specification:**
- Endpoint: `POST /mcp` (Streamable HTTP)
- Transport: SSE for streaming responses
- Dependency: `django-mcp-server==0.1.0`

**Current State:**
- ⚠️ Dependency installed but **not configured**
- App skeleton exists: `mcp/` app
- ASGI configuration ready in `cyberbrain_orchestrator/asgi.py`

**Rationale:**
- Standard protocol for AI agent integration
- Streaming responses for long-running operations
- Tool/resource discovery for external agents
- Integration with Claude Desktop, Cline, Windsurf, etc.

## Infrastructure & Deployment

### 7. Docker Socket Passthrough for Worker Spawning
**Decision:** Orchestrator accesses host Docker daemon via `/var/run/docker.sock` to spawn ephemeral worker containers for each task execution.

**Docker Compose Mount:**
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

**Workflow:**
1. Run created → Jobs spawned
2. Each job spawns a Docker worker container
3. Worker executes task (log_triage, gpu_report, service_map)
4. Worker writes results to shared volume
5. Orchestrator collects results, updates job status
6. Worker container removed on completion

**Security:**
- Worker containers MUST be from `WorkerImageAllowlist`
- Containers MUST be in `ContainerAllowlist` to be inspected
- No privileged mode for workers
- Read-only mounts where possible

### 8. Worker Allowlists (Security Control)
**Decision:** Two-tier allowlist system controls which containers can be spawned and inspected.

**Allowlist 1: WorkerImageAllowlist** (Phase 1 - `core/models.py`)
- Controls which Docker images can be spawned as workers
- Fields: `image_name`, `image_tag`, `requires_gpu`, `min_vram_mb`
- Unique constraint on `(image_name, image_tag)`

**Allowlist 2: ContainerAllowlist** (Legacy - `orchestrator/models.py`)
- Controls which running containers can be inspected (for Tasks 2 & 3)
- Fields: `container_id` (unique), `name`, `is_active`
- Used by `OrchestratorService.is_container_allowed()`

**Rationale:**
- Prevents arbitrary code execution via malicious images
- Limits attack surface for container inspection
- Audit trail via `WorkerAudit` model (Phase 1)
- GPU resource management (allocate to trusted images only)

### 9. Network Binding: HOST IP:9595
**Decision:** Application binds to `HOST IP:9595` (all interfaces; LAN-only assumed, no hardcoded IP pinning).

**Docker Compose:**
```yaml
ports:
  - "9595:8000"
```

**ASGI Server (Daphne):**
```
daphne -b 0.0.0.0 -p 8000 cyberbrain_orchestrator.asgi:application
```

**Access Pattern:**
- Replace `<UNRAID_HOST>` in examples with the actual Unraid LAN IP (e.g., `192.168.1.3`) or hostname
- Example: `http://192.168.1.3:9595` or `http://unraid.local:9595`

**Rationale:**
- Avoids hardcoding IPs in docker-compose / config
- Simplifies deployment across different networks
- Supports both IP and hostname access
- Docker remaps to all available host interfaces

**Implications:**
- LAN-only access (no TLS/internet exposure in this design)
- Host port 9595 must be available
- Configure firewall to restrict to trusted networks as needed

### 10. PostgreSQL in Docker Compose
**Decision:** Use PostgreSQL 16 Alpine in Docker Compose stack (not external managed database).

**Configuration:**
```yaml
db:
  image: postgres:16-alpine
  volumes:
    - postgres_data:/var/lib/postgresql/data
  environment:
    - POSTGRES_DB=${POSTGRES_DB:-cyberbrain_db}
    - POSTGRES_USER=${POSTGRES_USER:-cyberbrain_user}
    - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-changeme}
```

**Rationale:**
- Self-contained deployment (no external dependencies)
- Version consistency across environments
- Simple backup/restore via volume snapshots
- Health checks ensure DB ready before web service starts

**Not Supported:**
- External PostgreSQL instances (e.g., AWS RDS)
- MySQL/MariaDB (PostgreSQL-specific features used)
- SQLite for production (testing only via `test_settings.py`)

## Task & Directive System

### 11. Three Core Tasks (Task 1-3)
**Decision:** System supports exactly three task types with predefined workflows.

**Task 1: Log Triage** (`log_triage` / `task1`)
- Analyzes logs from `CYBER_BRAIN_LOGS` directory
- Identifies errors, warnings, anomalies
- Generates structured summary
- Phase 1 feature: "Since last successful run" windowing

**Task 2: GPU Report** (`gpu_report` / `task2`)
- Queries containers for GPU utilization
- Collects VRAM usage, temperature, utilization %
- Generates capacity planning report
- Only inspects containers in `ContainerAllowlist`

**Task 3: Service Map** (`service_map` / `task3`)
- Maps running services and dependencies
- Analyzes container network connections
- Generates service topology diagram
- Basis for dependency impact analysis

**Nomenclature Variance:**
- Legacy system (`orchestrator/`): `log_triage`, `gpu_report`, `service_map`
- Phase 1 system (`core/`): `task1`, `task2`, `task3`
- Both conventions coexist during migration

### 12. Default Directives (D1-D4)
**Decision:** Four directive types provide task templates and configurations.

**D1: Log Triage Directive**
- Pre-configured Task 1 execution
- Default log patterns, severity thresholds

**D2: GPU Report Directive**
- Pre-configured Task 2 execution
- Default GPU metrics, alert thresholds

**D3: Service Map Directive**
- Pre-configured Task 3 execution
- Default network topology settings

**D4: Custom Directives**
- User-defined task combinations
- Arbitrary task_config JSON
- Versioning support for directive evolution

**Phase 1 Enhancement:**
- Directives stored as **snapshots** via `Run.directive_snapshot_name` and `Run.directive_snapshot_text`
- Preserves exact configuration even if directive changes later
- Enables "what configuration was used for this run?" queries

## Environment Variables

### Required Configuration
```bash
# Log and upload directories
CYBER_BRAIN_LOGS=/path/to/logs       # Default: ./logs
CYBER_BRAIN_UPLOADS=/path/to/uploads # Default: ./uploads (rename from UPLOADS_DIR)

# Security
DEBUG_REDACTED_MODE=True             # Default: True

# Database (docker-compose)
POSTGRES_DB=cyberbrain_db
POSTGRES_USER=cyberbrain_user
POSTGRES_PASSWORD=secure_password_here

# Django
DJANGO_SECRET_KEY=generate_secure_key
DJANGO_DEBUG=False                   # Never True in production
```

## Migration Status

### ✅ Completed
- Django 5.1.14 security upgrade
- PostgreSQL 16 in docker-compose
- Docker socket integration
- Token-only LLM tracking
- DEBUG_REDACTED_MODE setting
- Phase 1 models in `core/` app
- Worker allowlist models

### ⚠️ In Progress
- ASGI server deployment (Gunicorn → Daphne/Uvicorn)
- MCP endpoint configuration
- Directive snapshot usage in API
- "Since last successful run" queries

### 📋 Planned
- Full migration from `orchestrator/` to `core/` models
- Enhanced API endpoints using Phase 1 models
- Worker audit trail implementation
- Container inventory snapshots

## Enforcement & Compliance

### Code Review Checklist
- [ ] No new LLM prompt/response storage fields
- [ ] Worker images added to `WorkerImageAllowlist`
- [ ] Inspected containers added to `ContainerAllowlist`
- [ ] Migrations created for both `orchestrator/` and `core/` if needed
- [ ] Tests use `test_settings.py` (SQLite, not PostgreSQL)
- [ ] Environment variables documented if added
- [ ] Security guardrail comments maintained in models

### Validation Requirements
```bash
# Must pass before merge
python validate.py
python manage.py test --settings=cyberbrain_orchestrator.test_settings
python manage.py makemigrations --check --dry-run
```

## References
- Build plan: `docs/build-plan.md`
- Phase 1 status: `PHASE1_STATUS.md`
- Missing features: `MISSING_FEATURES.md`
- API documentation: `API_DOCS.md`
- Agent instructions: `.github/copilot-instructions.md`
