# Cyberbrain Orchestrator - Phase 1 Status

## 🎯 Cyber-Brain Build Plan Requirements

### Core Requirements
- [x] Django 5 + DRF
- [x] PostgreSQL in docker-compose
- [x] Bind to 192.168.1.3:9595
- [ ] ASGI server (Daphne/Uvicorn) - dependencies added, needs configuration
- [ ] MCP endpoint at /mcp with Streamable HTTP + SSE
- [x] Environment variables: CYBER_BRAIN_LOGS, CYBER_BRAIN_UPLOADS, DEBUG_REDACTED_MODE
- [x] No prompt/response storage (token counts only)
- [x] Optional redacted debug mode

## ✅ Completed (Security & Foundation)

###

 1. Security Upgrade
- **Django 5.1.4 → 5.1.14** ✅
  - Fixed SQL injection vulnerabilities
  - Fixed DoS vulnerabilities on Windows
  - All 9 reported vulnerabilities addressed

### 2. App Structure Refactor
Created modular Django app structure:
- **core/** - Enhanced models ✅
- **api/** - DRF endpoints (skeleton created)
- **webui/** - Web interface (skeleton created)
- **mcp/** - MCP integration (skeleton created)
- **orchestration/** - Worker orchestration ✅

### 3. Enhanced Models (core/models.py)
All models implemented with proper indexes and guardrails:

#### Directive ✅
- D1-D4 library (Log Triage, GPU Report, Service Map, Custom)
- Version control
- Task configuration JSON
- Indexed by type, active status, creation date

#### Job ✅
- Task 1-3 templates
- Default configurations
- Active/inactive status
- Indexed by task type

#### Run ✅
- **Directive snapshot** (not reference) ✅
- Success/failure status (not just "completed") ✅
- Token count aggregation ✅
- Markdown + JSON reports ✅
- Index for "since last successful run" queries ✅
- `get_last_successful_run()` class method ✅

#### RunJob ✅
- Links Run to Job template
- Individual job execution tracking
- Token counts per job
- Structured results (NO LLM content) ✅

#### LLMCall ✅
- **CRITICAL GUARDRAILS**: NO prompt/response storage ✅
- Token counts ONLY (prompt, completion, total) ✅
- Endpoint + model_id tracking ✅
- Call duration, success/error tracking ✅
- Indexed by run_job, model_id, endpoint, timestamp ✅

#### RunArtifact ✅
- File paths under /logs (not content) ✅
- Artifact types (log, report, data, other)
- File size and MIME type metadata
- Indexed by run and type

#### ContainerInventory ✅
- Container state snapshots ✅
- Snapshot data as JSON
- Optional link to Run
- Indexed by container_id, name, timestamp

#### ContainerAllowlist ✅
- **container_id as PRIMARY KEY** ✅
- container_name as metadata ✅
- Active/inactive status
- Tags for organization
- Indexed by active status and name

#### WorkerImageAllowlist ✅
- Docker image allowlist (security control)
- Image name + tag unique constraint
- GPU requirements (requires_gpu, min_vram_mb)
- Active/inactive status

#### WorkerAudit ✅
- Audit trail for ALL worker operations
- Operation types: spawn, start, stop, remove, error
- Container ID and image name
- GPU assignment and selection reason
- Config snapshot at operation time
- Success/failure tracking
- Indexed by run_job, operation, container_id

#### GPUState ✅
- GPU tracking for scheduling
- Total/used/free VRAM in MB
- Utilization percentage
- Active worker count
- `scheduling_score` property with weighted blend:
  - 60% VRAM headroom
  - 40% utilization
  - Lower score = better choice (most idle GPU first)

### 4. Worker Orchestration (orchestration/workers.py)
Complete implementation with all security controls:

#### WorkerOrchestrator Class ✅
- **Docker socket passthrough** at /var/run/docker.sock ✅
- **Worker image allowlist** enforcement ✅
- **No host mounts** except /logs (rw) and /uploads (ro) ✅
- **Full LAN network** (bridge mode) ✅
- **Per-task ephemeral workers** (remove=True) ✅
- **GPU scheduling**:
  - Weighted blend (60% VRAM headroom + 40% utilization) ✅
  - Most-idle GPU first ✅
  - Explicit GPU override support ✅
  - CPU fallback when VRAM insufficient ✅
- **Audit trail** for every worker operation ✅

#### Key Methods ✅
- `spawn_worker()` - Spawn ephemeral worker with GPU selection
- `stop_worker()` - Stop and clean up worker
- `list_active_workers()` - List running cyberbrain workers
- `cleanup_orphaned_workers()` - Remove exited containers
- `_select_gpu()` - Smart GPU selection with fallback
- `_is_image_allowed()` - Allowlist validation
- `_build_container_config()` - Secure container config
- `_audit()` - Create audit entries

### 5. Settings Configuration ✅
Updated `cyberbrain_orchestrator/settings.py`:
- Added all new apps to INSTALLED_APPS ✅
- Added `channels` for ASGI support ✅
- **ASGI_APPLICATION** = 'cyberbrain_orchestrator.asgi.application' ✅
- **DEBUG_REDACTED_MODE** environment variable ✅
- **CYBER_BRAIN_LOGS** environment variable ✅
- **CYBER_BRAIN_UPLOADS** environment variable (renamed from UPLOADS_DIR) ✅
- Comprehensive logging with app-level loggers ✅
- GUARDRAIL: Warning when redacted mode is off in production ✅

### 6. Dependencies ✅
Updated `requirements.txt`:
- Django==5.1.14 (security upgrade) ✅
- uvicorn[standard]==0.34.0 (ASGI server) ✅
- daphne==4.1.2 (ASGI server alternative) ✅
- channels==4.2.0 (async support) ✅
- django-mcp-server==0.1.0 (MCP integration) ✅

## 🚧 In Progress (Critical Path)

### 1. MCP Server Integration
**Priority: HIGH** - Required for MCP endpoint

Need to implement in `mcp/` app:
- [ ] `mcp/server.py` - MCP server setup with django-mcp-server
- [ ] `mcp/tools.py` - Safe MCP tools (launch_run, list_runs, etc.)
- [ ] `mcp/resources.py` - MCP resources
- [ ] `mcp/urls.py` - Route /mcp endpoint
- [ ] `.vscode/mcp.json` - Example configuration for Streamable HTTP + SSE

**MCP Tools** (must enforce directives D1-D4, no raw LLM content):
- `launch_run` - Launch orchestrator run
- `list_runs` - List runs with filters
- `get_run_report` - Get Markdown + JSON + token counts ONLY
- `list_directives` - List D1-D4 directives
- `set_allowlist` - Manage container allowlist
- `get_allowlist` - Get container allowlist

### 2. DRF API Endpoints
**Priority: HIGH** - Core functionality

Need to implement in `api/` app:
- [ ] `api/serializers.py` - DRF serializers for all models
- [ ] `api/views.py` - ViewSets with enhanced functionality:
  - [x] Directive CRUD (partially done in old orchestrator app)
  - [ ] Job CRUD
  - [ ] Create run with directive snapshot
  - [ ] List runs with "since last successful run" windowing
  - [ ] Run detail with Markdown + JSON + token totals
  - [ ] Container allowlist CRUD
  - [ ] Container inventory (all view)
  - [ ] Custom directive text support on run creation
- [ ] `api/urls.py` - API routing

### 3. Database Migrations
**Priority: HIGH** - Required for database schema

- [ ] Generate migrations for core models
- [ ] Apply migrations
- [ ] Test all models and relationships
- [ ] Seed initial data (D1-D4 directives, Task 1-3 jobs)

### 4. ASGI Configuration
**Priority: MEDIUM** - Required for MCP/SSE

- [ ] Update `cyberbrain_orchestrator/asgi.py` for channels
- [ ] Configure SSE support for MCP endpoint
- [ ] Test async functionality

### 5. Docker Configuration
**Priority: MEDIUM** - Deployment updates

- [ ] Update `docker-compose.yml`:
  - Replace Gunicorn with Daphne or Uvicorn
  - Update command to use ASGI server
  - Add CYBER_BRAIN_UPLOADS volume
  - Add DEBUG_REDACTED_MODE env var
- [ ] Update `Dockerfile`:
  - Install new dependencies
  - Use ASGI server

### 6. WebUI Updates
**Priority: LOW** - Can reuse existing

- [ ] Move templates from orchestrator/ to webui/
- [ ] Update views to use new core models
- [ ] Add MCP endpoint testing UI

## 📊 Statistics

### Code Written
- **Models**: ~600 lines (core/models.py)
- **Worker Orchestration**: ~430 lines (orchestration/workers.py)
- **Admin**: ~90 lines (core/admin.py)
- **Settings**: ~240 lines (settings.py)
- **Total New Code**: ~1,360 lines

### Files Created
- 6 new app directories (core, api, webui, mcp, orchestration + legacy orchestrator)
- 40 new Python files
- Enhanced models with 11 tables
- Complete worker orchestration system

### Security Improvements
- Upgraded Django (9 vulnerabilities fixed)
- Worker image allowlist
- No arbitrary host mounts
- Audit trail for all worker operations
- DEBUG_REDACTED_MODE guardrail
- No LLM content storage (enforced at model level)

## 🎯 Phase 1 Definition of Done

To reach Phase 1 "done", we need:

### Critical Path
1. ✅ Security upgrade (Django 5.1.14)
2. ✅ Enhanced models with all requirements
3. ✅ Worker orchestration with GPU scheduling
4. 🚧 MCP endpoint with safe tools
5. 🚧 DRF API with enhanced endpoints
6. 🚧 Database migrations
7. 🚧 ASGI configuration
8. 🚧 Docker updates for ASGI

### Nice to Have
- WebUI migration to new structure
- Comprehensive tests for new models
- Documentation updates

## 📅 Estimated Completion
- **MCP Integration**: ~2-3 hours
- **API Endpoints**: ~2-3 hours
- **Migrations & Testing**: ~1 hour
- **ASGI & Docker**: ~1 hour
- **Total**: ~6-10 hours remaining to Phase 1 "done"

## 🔐 Security & Guardrails Status

### ✅ Implemented
- No prompt/response storage (model-level enforcement)
- Token counts only for LLM tracking
- DEBUG_REDACTED_MODE environment variable
- Worker image allowlist
- Container allowlist
- Audit trail for all worker operations
- Secure volume mounts (only /logs and /uploads)

### 🚧 Pending
- MCP tools safety enforcement
- API endpoint input validation
- Rate limiting (future)
- Authentication (future - currently AllowAny)
