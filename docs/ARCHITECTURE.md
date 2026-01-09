# Cyberbrain Orchestrator - Architecture Documentation

## System Overview

Cyberbrain Orchestrator is a Django 5 task orchestration system for managing Docker container workflows with LLM integration.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client Layer                             │
│  (HTTP/REST API, Swagger UI, Web Browser)                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Django Application                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  DRF API     │  │  Metrics     │  │  OpenAPI     │         │
│  │  Views       │  │  System      │  │  Schema      │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│  ┌──────────────────────────────────────────────────┐           │
│  │          Orchestration Layer                      │           │
│  │  - Task Workers (log_triage, gpu_report, etc)    │           │
│  │  - Docker Client Integration                      │           │
│  │  - LLM Client Integration                         │           │
│  └──────────────────────────────────────────────────┘           │
│  ┌──────────────────────────────────────────────────┐           │
│  │          Data Layer (Django ORM)                  │           │
│  │  - Runs, Jobs, Directives                        │           │
│  │  - Artifacts, LLM Calls                          │           │
│  │  - Container Allowlist                            │           │
│  └──────────────────────────────────────────────────┘           │
└────────┬────────────────────────────┬─────────────────┬─────────┘
         │                            │                 │
         ▼                            ▼                 ▼
┌─────────────────┐        ┌──────────────────┐  ┌──────────────┐
│   PostgreSQL    │        │  Docker Socket   │  │  LLM Server  │
│   Database      │        │  /var/run/       │  │  (vLLM,      │
│                 │        │  docker.sock     │  │  llama.cpp)  │
└─────────────────┘        └──────────────────┘  └──────────────┘
         │                            │
         ▼                            ▼
┌─────────────────┐        ┌──────────────────┐
│  /logs          │        │  Running Docker  │
│  /uploads       │        │  Containers      │
│  (Artifacts)    │        │  (monitored)     │
└─────────────────┘        └──────────────────┘
```

## Component Details

### API Layer

**Technology**: Django REST Framework 3.15  
**Responsibilities**:
- HTTP request handling
- Request/response serialization
- Authentication & authorization (currently AllowAny)
- API documentation (Swagger/ReDoc)

**Key Endpoints**:
- `/api/runs/` - Run CRUD operations
- `/api/runs/launch/` - Launch new runs
- `/api/artifacts/` - Artifact management
- `/api/token-stats/` - Token accounting
- `/metrics/` - Prometheus metrics

### Orchestration Layer

**Components**:

1. **Task Workers** (`orchestration/task_workers.py`)
   - Log Triage: Analyze container logs
   - GPU Report: Monitor GPU usage
   - Service Map: Generate service topology
   
2. **Docker Client** (`orchestration/docker_client.py`)
   - Log collection from containers
   - Container discovery
   - Allowlist enforcement
   
3. **LLM Client** (`orchestration/llm_client.py`)
   - OpenAI-compatible API integration
   - Token counting and tracking
   - Error handling and retries

### Data Models

**Legacy Models** (`orchestrator/models.py`):
- `Directive` - Task configuration templates
- `Run` - Execution instances
- `Job` - Individual task executions
- `LLMCall` - Token tracking (legacy)
- `ContainerAllowlist` - Approved containers

**Phase 1 Models** (`core/models.py`):
- `Directive` - Enhanced with versioning
- `Job` - Task templates
- `Run` - Directive snapshots
- `RunJob` - Run execution tracking
- `LLMCall` - Enhanced token tracking
- `RunArtifact` - Output file tracking
- `ContainerInventory` - Container metadata
- `WorkerImageAllowlist` - Approved images

### Storage Layer

**PostgreSQL Database**:
- Runs, Jobs, Directives
- LLM call metadata (NO prompts/responses)
- Artifact metadata (paths only)

**Filesystem**:
- `/logs` - Container logs, analysis results
- `/uploads` - User-uploaded files (future)

**Docker Socket**:
- `/var/run/docker.sock` - Container access

## Data Flow Diagrams

### Run Execution Flow

```
Client
  │
  │ POST /api/runs/launch/
  │ {tasks: ['log_triage']}
  │
  ▼
API Layer
  │ 1. Validate request
  │ 2. Create Run record
  │ 3. Create Job records
  │ 4. Record metrics
  │
  ▼
[Run created, pending]
  │
  │ (Worker process - future)
  │
  ▼
Task Worker (log_triage)
  │
  │ 1. Get enabled containers
  │    from ContainerAllowlist
  │
  ▼
Docker Client
  │ 2. Collect logs from
  │    each container
  │
  ▼
LLM Client
  │ 3. Analyze logs with LLM
  │ 4. Record token counts
  │
  ▼
Artifact Storage
  │ 5. Write analysis to /logs
  │ 6. Create Artifact records
  │
  ▼
[Run completed]
```

### Token Accounting Flow

```
LLM API Call
  │
  │ Complete(prompt, model, max_tokens)
  │
  ▼
LLM Server Response
  │ {
  │   "choices": [...],
  │   "usage": {
  │     "prompt_tokens": 100,
  │     "completion_tokens": 50,
  │     "total_tokens": 150
  │   }
  │ }
  │
  ▼
LLMClient.complete()
  │ Extract token counts
  │ (NO prompt/response storage)
  │
  ▼
Database: core.LLMCall
  │ Store: model_id, endpoint,
  │        prompt_tokens, completion_tokens,
  │        total_tokens
  │
  ▼
Metrics System
  │ Record: llm_tokens_total,
  │         llm_calls_total
  │
  ▼
Cost Report API
  │ GET /api/cost-report/
  │ Calculate costs by model
```

### Artifact Retrieval Flow

```
Client
  │
  │ GET /api/runs/{id}/artifacts/
  │
  ▼
API: RunViewSet.artifacts()
  │ Query RunArtifact.objects
  │ Filter by run_id
  │
  ▼
Response: [
  {
    "id": 1,
    "artifact_type": "analysis_report",
    "path": "/logs/run_123/analysis.json",
    "created_at": "2026-01-08T..."
  }
]
  │
  │ (Optional download)
  │ GET /api/artifacts/{id}/download/
  │
  ▼
API: RunArtifactViewSet.download()
  │ 1. Verify path in /logs/
  │ 2. Check file exists
  │ 3. Serve via FileResponse
```

## Security Architecture

### Defense in Depth

```
┌─────────────────────────────────────────────────┐
│ Layer 1: Network Security                       │
│ - Firewall rules                                │
│ - HTTPS/TLS encryption                          │
│ - Rate limiting                                 │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│ Layer 2: Application Security                   │
│ - ALLOWED_HOSTS validation                      │
│ - CSRF protection                               │
│ - SQL injection prevention (ORM)                │
│ - XSS protection (auto-escaping)                │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│ Layer 3: Data Security                          │
│ - LLM content NEVER stored                      │
│ - DEBUG_REDACTED_MODE for sensitive data        │
│ - Artifact path restriction (/logs only)        │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│ Layer 4: Container Security                     │
│ - ContainerAllowlist enforcement                │
│ - Docker socket access control                  │
│ - Read-only filesystem (where applicable)       │
└─────────────────────────────────────────────────┘
```

### Security Guardrails

**LLM Content Storage Prevention**:
- `LLMCall` model has NO `prompt` or `response` fields
- Only token counts stored
- Code comments warn against adding content fields
- Acceptance tests verify no content storage

**Container Access Control**:
- All Docker operations check `ContainerAllowlist.is_active=True`
- Unauthorized container access returns error
- Allowlist managed via API or Django admin

**Artifact Access Control**:
- All artifact downloads verify `path.startswith('/logs/')`
- Prevents directory traversal attacks
- Returns 404 for unauthorized paths

## Observability Architecture

### Metrics System

**Storage**: Django cache (default: in-memory)  
**Format**: Prometheus-compatible text + JSON  
**Endpoints**:
- `/metrics/` - Prometheus scrape endpoint
- `/metrics/json/` - JSON metrics for dashboards

**Metric Types**:
- **Counters**: runs_created_total, jobs_created_total, llm_tokens_total
- **Gauges**: active_runs
- **Histograms**: jobs_duration_seconds, api_request_duration_seconds

### Structured Logging

**Format**: JSON  
**Handler**: RotatingFileHandler  
**Fields**:
- `timestamp` (ISO 8601 UTC)
- `level` (INFO, WARNING, ERROR)
- `logger` (module name)
- `message`
- `run_id`, `job_id`, `task_key` (contextual)

### Monitoring Stack Integration

```
┌──────────────────┐
│  Cyberbrain Web  │
│  /metrics/       │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Prometheus     │
│   (Scraping)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│    Grafana       │
│   (Dashboards)   │
└──────────────────┘

┌──────────────────┐
│  Cyberbrain Web  │
│  JSON Logs       │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Log Aggregator  │
│  (ELK, Splunk)   │
└──────────────────┘
```

## Deployment Architecture

### Docker Compose Setup

```
┌─────────────────────────────────────────────────────┐
│                  Docker Host                         │
│                                                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │  web       │  │  db        │  │  nginx     │    │
│  │  (Django)  │  │  (Postgres)│  │  (proxy)   │    │
│  │  :8000     │  │  :5432     │  │  :80,:443  │    │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘    │
│        │               │               │            │
│        │               │               │            │
│  ┌─────▼───────────────▼───────────────▼──────┐    │
│  │         cyberbrain network                  │    │
│  └─────────────────────────────────────────────┘    │
│                                                       │
│  Volumes:                                            │
│  - postgres_data                                     │
│  - static_files                                      │
│  - /logs (host mount)                               │
│  - /var/run/docker.sock (host mount)               │
└─────────────────────────────────────────────────────┘
```

## Future Architecture Considerations

### Phase 2 Enhancements

1. **Worker Separation**: Background Celery workers for task execution
2. **Redis Integration**: Cache + message queue
3. **WebSocket Support**: Real-time run status updates (via Channels)
4. **MCP Server**: Model Context Protocol endpoint
5. **Multi-tenancy**: Organization/user isolation

### Scalability Roadmap

```
Current: Single web process
  │
  ▼
Phase 2: Multiple web workers + Celery
  │
  ▼
Phase 3: Kubernetes deployment
  │
  ▼
Phase 4: Multi-region, geo-distributed
```

## Technology Stack

- **Framework**: Django 5.1.14
- **API**: Django REST Framework 3.15.2
- **Database**: PostgreSQL 16
- **ASGI Server**: Daphne 4.1.2
- **Container Runtime**: Docker 20.10+
- **Python**: 3.12

## References

- [API Documentation](../API_DOCS.md)
- [Deployment Guide](./DEPLOYMENT.md)
- [Phase 1 Status](../PHASE1_STATUS.md)
- [Missing Features](../MISSING_FEATURES.md)
