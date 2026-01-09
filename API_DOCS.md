# Cyberbrain Orchestrator API Documentation

## Base URL
```
http://<UNRAID_HOST>:9595/api/
```

Replace `<UNRAID_HOST>` with your Unraid LAN IP (e.g., `192.168.1.3`) or hostname.

## Authentication
Currently, the API is open (AllowAny permission). In production, you should implement proper authentication.

---

## Endpoints

### Directives

#### List Directives
```http
GET /api/directives/
```

**Response:**
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "default",
      "description": "Default orchestrator directive",
      "task_config": {},
      "created_at": "2026-01-08T16:00:00Z",
      "updated_at": "2026-01-08T16:00:00Z"
    }
  ]
}
```

#### Create Directive
```http
POST /api/directives/
Content-Type: application/json

{
  "name": "custom_directive",
  "description": "Custom orchestrator configuration",
  "task_config": {
    "timeout": 300,
    "retries": 3
  }
}
```

#### Get Directive
```http
GET /api/directives/{id}/
```

#### Update Directive
```http
PUT /api/directives/{id}/
PATCH /api/directives/{id}/
```

#### Delete Directive
```http
DELETE /api/directives/{id}/
```

---

### Runs

#### List Runs
```http
GET /api/runs/
```

**Response:**
```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "directive": 1,
      "directive_name": "default",
      "status": "completed",
      "started_at": "2026-01-08T16:00:00Z",
      "completed_at": "2026-01-08T16:05:00Z",
      "job_count": 3
    }
  ]
}
```

#### Get Run Details
```http
GET /api/runs/{id}/
```

**Response:**
```json
{
  "id": 1,
  "directive": 1,
  "directive_name": "default",
  "status": "completed",
  "started_at": "2026-01-08T16:00:00Z",
  "completed_at": "2026-01-08T16:05:00Z",
  "report_markdown": "# Orchestrator Run #1\n...",
  "report_json": {
    "run_id": 1,
    "status": "completed",
    "jobs": [...]
  },
  "error_message": "",
  "jobs": [
    {
      "id": 1,
      "task_type": "log_triage",
      "status": "completed",
      "started_at": "2026-01-08T16:00:00Z",
      "completed_at": "2026-01-08T16:02:00Z",
      "result": {
        "task": "log_triage",
        "status": "completed",
        "summary": "Log triage completed"
      },
      "error_message": "",
      "llm_calls": []
    }
  ]
}
```

#### Launch Run
```http
POST /api/runs/launch/
Content-Type: application/json

{
  "directive_id": 1,  // Optional, defaults to "default" directive
  "tasks": ["log_triage", "gpu_report", "service_map"]  // Optional, defaults to all tasks
}
```

```bash
curl -X POST http://<UNRAID_HOST>:9595/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{}'
```

```bash
curl -X POST http://<UNRAID_HOST>:9595/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{"tasks": ["log_triage", "gpu_report"]}'
```

**Response:**
```json
{
  "id": 1,
  "directive": 1,
  "directive_name": "default",
  "status": "pending",
  "started_at": "2026-01-08T16:00:00Z",
  "completed_at": null,
  "report_markdown": "",
  "report_json": {},
  "error_message": "",
  "jobs": [
    {
      "id": 1,
      "task_type": "log_triage",
      "status": "pending",
      "started_at": null,
      "completed_at": null,
      "result": {},
      "error_message": "",
      "llm_calls": []
    },
    {
      "id": 2,
      "task_type": "gpu_report",
      "status": "pending",
      "started_at": null,
      "completed_at": null,
      "result": {},
      "error_message": "",
      "llm_calls": []
    },
    {
      "id": 3,
      "task_type": "service_map",
      "status": "pending",
      "started_at": null,
      "completed_at": null,
      "result": {},
      "error_message": "",
      "llm_calls": []
    }
  ]
}
```

#### Get Run Report
```http
GET /api/runs/{id}/report/
```

**Response:**
```json
{
  "id": 1,
  "status": "completed",
  "markdown": "# Orchestrator Run #1\n\n**Status:** Completed\n**Started:** 2026-01-08 16:00:00\n\n## Jobs\n\n### ✅ log_triage\n- Job ID: 1\n- Status: Success\n- Summary: Log triage task executed\n\n### ✅ gpu_report\n- Job ID: 2\n- Status: Success\n- Summary: GPU report generated\n\n### ✅ service_map\n- Job ID: 3\n- Status: Success\n- Summary: Service map generated\n",
  "json": {
    "run_id": 1,
    "status": "completed",
    "started_at": "2026-01-08T16:00:00Z",
    "jobs": [
      {
        "job_id": 1,
        "task_type": "log_triage",
        "success": true,
        "result": {
          "task": "log_triage",
          "status": "completed",
          "summary": "Log triage task executed"
        }
      }
    ]
  },
  "started_at": "2026-01-08T16:00:00Z",
  "completed_at": "2026-01-08T16:05:00Z"
}
```

---

### Jobs

#### List Jobs
```http
GET /api/jobs/
```

**Query Parameters:**
- `run`: Filter by run ID

**Example:**
```bash
curl http://<UNRAID_HOST>:9595/api/jobs/?run=1
```

#### Get Job Details
```http
GET /api/jobs/{id}/
```

---

### Container Allowlist

#### List Containers
```http
GET /api/containers/
```

**Response:**
```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "container_id": "abc123def456",
      "name": "my-container",
      "description": "Production container",
      "created_at": "2026-01-08T16:00:00Z",
      "is_active": true
    }
  ]
}
```

#### Add Container to Allowlist
```http
POST /api/containers/
Content-Type: application/json

{
  "container_id": "abc123def456",
  "name": "my-container",
  "description": "Production container",
  "is_active": true
}
```

**Example:**
```bash
curl -X POST http://<UNRAID_HOST>:9595/api/containers/ \
  -H "Content-Type: application/json" \
  -d '{
    "container_id": "abc123def456",
    "name": "my-container",
    "description": "Production container"
  }'
```

#### Update Container
```http
PUT /api/containers/{id}/
PATCH /api/containers/{id}/
```

**Example: Deactivate container**
```bash
curl -X PATCH http://<UNRAID_HOST>:9595/api/containers/1/ \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

#### Delete Container
```http
DELETE /api/containers/{id}/
```

---

## Task Types

The orchestrator supports three task types:

1. **log_triage**: Analyzes logs from the `CYBER_BRAIN_LOGS` directory
2. **gpu_report**: Queries Docker containers for GPU information
3. **service_map**: Maps running services and their relationships

---

## Status Values

### Run/Job Status
- `pending`: Task is queued but not started
- `running`: Task is currently executing
- `completed`: Task finished successfully
- `failed`: Task encountered an error

---

## Executing Runs

To actually execute a run (not just create it), use the management command:

```bash
# Via Docker
docker-compose exec web python manage.py run_orchestrator <run_id>

# Locally
python manage.py run_orchestrator <run_id>
```

---

## WebUI

Access the web interface at:
```
http://<UNRAID_HOST>:9595/
```

The WebUI provides:
- Quick launch buttons for common task combinations
- Real-time run listing
- Report viewing with markdown and JSON formats
- API endpoint reference

---

## Error Responses

### 400 Bad Request
```json
{
  "error": "Invalid request data",
  "details": {...}
}
```

### 404 Not Found
```json
{
  "detail": "Not found."
}
```

### 500 Internal Server Error
```json
{
  "error": "Internal server error",
  "message": "..."
}
```
