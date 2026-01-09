# Phase 1 Smoke Test

## Overview

The Phase 1 smoke test validates all acceptance criteria for the Cyberbrain Orchestrator MVP. It performs end-to-end verification of:

- Infrastructure (docker-compose, web, database)
- API endpoints (WebUI, REST API, MCP)
- Data models (Directives, Jobs, Runs)
- Security guardrails (token counting only, no prompt storage)
- Core functionality (task launches, artifacts, windowing)

## Prerequisites

Before running the smoke test, ensure:

1. **Docker and docker-compose are installed**
   ```bash
   docker --version
   docker-compose --version
   ```

2. **The stack is running**
   ```bash
   cd /home/ssanders/Code/cyberbrain-orchestrator
   docker-compose up -d
   ```

3. **Database migrations are applied**
   ```bash
   docker-compose exec web /opt/venv/bin/python manage.py migrate
   ```

4. **The application is accessible**
   - WebUI: http://localhost:9595/
   - API: http://localhost:9595/api/

## Running the Smoke Test

### Option 1: From VS Code (Recommended)

1. Open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`)
2. Type "Tasks: Run Task"
3. Select **"Phase 1: Smoke Test"**

The test will run in the integrated terminal and display results.

### Option 2: From Terminal (Local Python)

```bash
cd /home/ssanders/Code/cyberbrain-orchestrator
python3 scripts/smoke_phase1.py
```

### Option 3: Inside Docker Container

```bash
cd /home/ssanders/Code/cyberbrain-orchestrator
docker-compose exec web /opt/venv/bin/python /app/scripts/smoke_phase1.py
```

Or use VS Code task: **"Phase 1: Smoke Test (in container)"**

## What the Test Validates

### 1. Infrastructure
- ✓ Docker compose stack is running (web + db services)
- ✓ Both containers are in "running" state
- ✓ Services are healthy

### 2. Web Interfaces
- ✓ WebUI responds on `/` (HTTP 200)
- ✓ API responds on `/api/` (HTTP 200)
- ✓ MCP endpoint responds on `/mcp` (HTTP 200)

### 3. MCP Endpoint
- ✓ Returns JSON response
- ✓ Includes `tools` array
- ✓ Lists available MCP tools (launch, list, get, report, etc.)

### 4. Directive Library (D1-D4)
- ✓ D1: Read-only Diagnostics
- ✓ D2: Conservative Recommendations
- ✓ D3: Change Planning
- ✓ D4: Admin Override
- Creates missing directives if not found

### 5. Job Templates (Task1/2/3)
- ✓ Task 1: log_triage (LLM log analysis)
- ✓ Task 2: gpu_report (GPU/VRAM monitoring)
- ✓ Task 3: service_map (Container inventory)

### 6. Container Allowlist
- ✓ API endpoint functional
- ✓ Can read allowlist entries
- ✓ Can create new entries (if permissions allow)

### 7. Task Launches
- ✓ Can launch Task1 via `/api/runs/launch/`
- ✓ Can launch Task2
- ✓ Can launch Task3
- ✓ Receives valid run IDs

### 8. Security Guardrails
- ✓ Token accounting only (no prompt/response storage)
- ✓ No suspicious fields (prompt, response, llm_content) in API
- ✓ Token stats endpoint returns counts only

### 9. Windowing
- ✓ `/api/runs/since-last-success/` endpoint exists
- ✓ Returns last successful run timestamp
- ✓ Returns runs since last success

## Understanding Results

### PASS (Exit Code 0)
```
======================================================================
SMOKE TEST RESULTS: 12 passed, 0 failed
======================================================================
✅ ALL SMOKE TESTS PASSED
```

**Meaning**: All Phase 1 acceptance criteria are met. The system is ready for use.

### FAIL (Exit Code 1)
```
======================================================================
SMOKE TEST RESULTS: 10 passed, 2 failed
======================================================================
❌ 2 SMOKE TESTS FAILED
```

**Meaning**: One or more criteria failed. Check the log output for specific errors.

Common failures:
- **Docker compose not running**: Start with `docker-compose up -d`
- **Database not migrated**: Run `docker-compose exec web python manage.py migrate`
- **Port conflict**: Ensure port 9595 is available
- **Missing directives**: Script will auto-create, but check permissions

### Warnings
```
⚠ WARNING: Missing task types: {'service_map'}
```

**Meaning**: Non-critical issues detected. System may still be functional but some features are incomplete.

## Troubleshooting

### Error: "Connection refused to http://localhost:9595"

**Cause**: Docker compose stack is not running or not bound to localhost.

**Fix**:
```bash
docker-compose up -d
docker-compose ps  # Verify services are running
```

### Error: "docker-compose command not found"

**Cause**: Docker Compose is not installed or not in PATH.

**Fix**: Install Docker Compose:
```bash
# Linux
sudo apt-get install docker-compose

# macOS (via Homebrew)
brew install docker-compose
```

### Error: "Web service not running"

**Cause**: Web container failed to start.

**Fix**: Check logs:
```bash
docker-compose logs web
docker-compose up web  # Start interactively to see errors
```

Common issues:
- Port 9595 already in use
- Database connection failed
- Missing environment variables

### Error: "Directive library missing D1-D4"

**Cause**: Database not seeded with initial directives.

**Fix**: Script will auto-create directives. If it fails, create manually:
```bash
docker-compose exec web /opt/venv/bin/python manage.py shell
```

Then in Python shell:
```python
from core.models import Directive
Directive.objects.create(directive_type='D1', name='Read-only Diagnostics', is_builtin=True)
# Repeat for D2, D3, D4
```

### Error: "Jobs for Task1/2/3 missing"

**Cause**: Job templates not created in database.

**Fix**: Jobs may need fixtures or manual creation. This is a warning, not a blocker for smoke test.

## Next Steps After PASS

1. **Explore the WebUI**: http://localhost:9595/
2. **Try the API**: http://localhost:9595/api/docs/ (Swagger UI)
3. **Launch a real task**: Use the WebUI or API to launch Task1
4. **Review artifacts**: Check `/logs` directory for outputs
5. **Monitor tokens**: Check `/api/token-stats/` for usage

## Continuous Integration

To run the smoke test in CI/CD pipelines:

```bash
#!/bin/bash
set -e

# Start stack
docker-compose up -d

# Wait for health
sleep 10

# Run migrations
docker-compose exec -T web /opt/venv/bin/python manage.py migrate

# Run smoke test
docker-compose exec -T web /opt/venv/bin/python /app/scripts/smoke_phase1.py

# Capture exit code
EXIT_CODE=$?

# Cleanup
docker-compose down

exit $EXIT_CODE
```

## Smoke Test vs Full Test Suite

| Aspect | Smoke Test | Full Test Suite |
|--------|------------|----------------|
| **Purpose** | Quick validation of Phase 1 criteria | Comprehensive unit/integration tests |
| **Duration** | < 30 seconds | 30-40 seconds |
| **Coverage** | End-to-end acceptance | All code paths |
| **When to run** | After deployment, before using system | Before commits, in CI/CD |
| **Exit on failure** | Fast fail on first critical error | Runs all tests regardless |

## Files

- **Smoke Test Script**: `scripts/smoke_phase1.py`
- **VS Code Tasks**: `.vscode/tasks.json`
- **Documentation**: `docs/SMOKE_TEST.md` (this file)

## Support

For issues with the smoke test:
1. Check logs: `docker-compose logs web`
2. Verify stack: `docker-compose ps`
3. Review documentation: `docs/DEPLOYMENT.md`
4. Check GitHub issues: https://github.com/malgorath/cyberbrain-orchestrator/issues

---

**Last Updated**: January 8, 2026
**Phase 1 Status**: Complete ✅
