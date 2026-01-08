# Cyber-Brain Build Plan - Gap Analysis

## ✅ Already Implemented
- [x] Django 5 project structure
- [x] PostgreSQL in docker-compose
- [x] Bind to 192.168.1.3:9595
- [x] Basic DRF endpoints
- [x] Simple WebUI
- [x] Basic models (Directive, Run, Job, LLMCall, ContainerAllowlist)
- [x] No prompt storage (token counts only)
- [x] Docker socket access
- [x] Environment variables for logs/uploads

## ❌ Missing Features (Phase 1 Critical)

### 1. ASGI Server
- [ ] Replace Gunicorn with Uvicorn/Daphne for async support
- [ ] Configure ASGI application in settings
- [ ] Update docker-compose to use ASGI server

### 2. MCP Endpoint
- [ ] Integrate django-mcp-server
- [ ] Implement /mcp endpoint with Streamable HTTP
- [ ] Add SSE (Server-Sent Events) support
- [ ] Configure MCP tools/resources

### 3. App Structure Refactor
- [ ] Create 'core' app for models
- [ ] Create 'api' app for DRF endpoints
- [ ] Create 'webui' app for templates
- [ ] Create 'mcp' app for MCP integration
- [ ] Create 'orchestration' app for worker spawn

### 4. Enhanced Models
- [ ] Add RunArtifact model (file paths under /logs)
- [ ] Add ContainerInventory model (snapshots)
- [ ] Enhance ContainerAllowlist (container_id as primary key)
- [ ] Add directive snapshot field to Run
- [ ] Add indexes for "since last successful run" queries
- [ ] Add proper status tracking for success/failure

### 5. Environment Variables
- [ ] CYBER_BRAIN_LOGS (already done, but needs validation)
- [ ] CYBER_BRAIN_UPLOADS (rename from UPLOADS_DIR)
- [ ] DEBUG_REDACTED_MODE (new, default off)
- [ ] Proper settings structure to read all env vars

### 6. Enhanced API Endpoints
- [ ] Directive snapshot stored on Run record
- [ ] "Since last successful run" windowing for Task 1
- [ ] Better run detail endpoint (Markdown + JSON + token totals)
- [ ] Inventory containers endpoint (all view)
- [ ] Create run with custom directive text

### 7. Guardrails
- [ ] Add comments warning against LLM content storage
- [ ] Implement redacted debug mode
- [ ] Ensure no prompts/responses stored anywhere

## Minimal File-Level Checklist for Phase 1 "Done"

### New Apps to Create
```
cyberbrain_orchestrator/
├── core/              # NEW: Core models and business logic
│   ├── __init__.py
│   ├── models.py      # All database models
│   ├── admin.py       # Admin interface
│   └── migrations/
├── api/               # NEW: DRF API endpoints
│   ├── __init__.py
│   ├── views.py       # API viewsets
│   ├── serializers.py # DRF serializers
│   └── urls.py        # API routing
├── webui/             # NEW: Web interface
│   ├── __init__.py
│   ├── views.py       # Web views
│   ├── urls.py        # Web routing
│   └── templates/     # HTML templates
├── mcp/               # NEW: MCP server integration
│   ├── __init__.py
│   ├── server.py      # MCP server setup
│   ├── tools.py       # MCP tools
│   ├── resources.py   # MCP resources
│   └── urls.py        # MCP endpoints
└── orchestration/     # NEW: Worker/task execution
    ├── __init__.py
    ├── workers.py     # Task workers
    ├── services.py    # Orchestration logic
    └── tasks.py       # Task definitions
```

### Files to Modify
- [ ] settings.py - Add ASGI config, new apps, env vars
- [ ] asgi.py - Configure ASGI application
- [ ] urls.py - Route to new apps
- [ ] docker-compose.yml - Use Daphne/Uvicorn
- [ ] Dockerfile - Update for ASGI
- [ ] requirements.txt - Add channels, daphne, django-mcp-server

### Files to Create
- [ ] core/models.py - Enhanced models with RunArtifact, ContainerInventory
- [ ] api/views.py - All DRF endpoints
- [ ] mcp/server.py - MCP endpoint implementation
- [ ] orchestration/workers.py - Task execution
- [ ] settings/base.py - Split settings (optional but recommended)

## Priority Order
1. **Security** - Upgrade Django (DONE)
2. **App Structure** - Refactor into proper apps
3. **Models** - Add missing models and indexes
4. **API** - Enhance endpoints
5. **ASGI** - Switch to async server
6. **MCP** - Add MCP endpoint
7. **Testing** - Update tests for new structure
