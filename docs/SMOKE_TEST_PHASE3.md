# Phase 3 RAG Smoke Test

## Overview
Comprehensive end-to-end test for Phase 3 RAG functionality, validating:
- File upload and ingestion pipeline
- RAG search with semantic similarity
- RAG integration with task execution (`use_rag=true`)
- MCP tools for RAG operations
- Security guardrails (query hashing, no prompt/response storage)

## Prerequisites
1. **Docker Compose services running:**
   ```bash
   docker-compose up -d
   ```

2. **Ingester worker running:**
   ```bash
   # In a separate terminal
   python manage.py run_ingester
   
   # OR run in Docker
   docker-compose exec web python manage.py run_ingester
   ```

3. **Database migrations applied:**
   ```bash
   python manage.py migrate
   ```

## Running the Smoke Test

### Option 1: Direct Python Execution
```bash
python3 scripts/smoke_phase3.py
```

### Option 2: VS Code Task
1. Open Command Palette (Ctrl+Shift+P / Cmd+Shift+P)
2. Select "Tasks: Run Task"
3. Choose "Phase 3: Smoke Test"

### Option 3: In Docker Container
```bash
docker-compose exec web /opt/venv/bin/python /app/scripts/smoke_phase3.py
```

## Test Flow
1. **Service Health Check** - Verify API is accessible
2. **Upload Test File** - Upload Django documentation snippet via RAG API
3. **Wait for Ingestion** - Poll upload status until `ready` (max 60s)
4. **Test RAG Search** - Query "Django web framework" and verify results
5. **Test MCP RAG Search** - Verify MCP endpoint returns search results
6. **Launch Run with RAG** - Create run with `use_rag=true`
7. **Wait for Completion** - Poll run status until completed (max 30s)
8. **Validate Report** - Confirm report markdown/JSON exists
9. **Validate LLM Guardrails** - Verify no prompt/response content stored
10. **Validate Query Privacy** - Confirm query hashing enforced
11. **Test MCP Launch** - Verify MCP can launch runs with `use_rag=true`

## PASS Criteria
Test passes when ALL of the following are true:

### Core Functionality (MUST PASS)
- ✅ Service responds to API requests
- ✅ File upload creates `UploadFile` record with `queued` status
- ✅ Ingestion completes within 60s (status changes to `ready`)
- ✅ RAG search returns at least 1 result with similarity score
- ✅ Run launches successfully with `use_rag=true` field set
- ✅ Run completes within 30s (status `completed`)
- ✅ Run report exists (markdown or JSON)

### Security Guardrails (MUST PASS)
- ✅ No prompt/response content in Job results
- ✅ Query text stored as SHA256 hash only (not plaintext)
- ✅ `RetrievalEvent` model has no `query_text` field
- ✅ LLM calls (if any) store token counts only

### Optional Features (MAY PASS)
- ⚠️ MCP RAG search returns results (depends on MCP configuration)
- ⚠️ MCP launch with RAG succeeds (depends on MCP configuration)
- ⚠️ RAG context actually used in job execution (depends on job implementation)

## Expected Output
### Successful Run
```
============================================================
  PHASE 3 RAG SMOKE TEST
============================================================

============================================================
  1. Service Health Check
============================================================
✓ Service is running

============================================================
  2. Upload Test File
============================================================
✓ File uploaded successfully (ID: 1)
  Status: queued
  Filename: test_django.txt

============================================================
  3. Wait for Ingestion
============================================================
  Status: queued
  Status: processing
  Status: ready
✓ Ingestion completed in 8s

============================================================
  4. Test RAG Search
============================================================
✓ Search completed
  Query hash: a3f8d2e91b4c7a...
  Results: 2
✓ Found 2 result(s)
  Top result score: 0.8543
  Snippet: Django is a high-level Python web framework that encourages rapid development...

... [additional tests] ...

============================================================
  TEST SUMMARY
============================================================
  ✓ Service health
  ✓ File upload
  ✓ Ingestion
  ✓ RAG search
  ✓ MCP RAG search
  ✓ Launch run with RAG
  ✓ Run completion
  ✓ Run report
  ✓ LLM call guardrails
  ✓ Query privacy
  ✓ MCP launch with RAG

============================================================
  ✓ PASS - All Phase 3 smoke tests passed!
============================================================
```

## Troubleshooting

### Issue: Upload fails with connection error
**Cause:** Service not running  
**Fix:** 
```bash
docker-compose up -d
# Wait 10s for services to start
docker-compose logs -f web
```

### Issue: Ingestion timeout after 60s
**Cause:** Ingester worker not running  
**Fix:**
```bash
# Terminal 1: Start ingester
python manage.py run_ingester

# Terminal 2: Re-run smoke test
python3 scripts/smoke_phase3.py
```

### Issue: No search results found
**Cause:** Ingestion failed or vector embeddings not generated  
**Fix:**
1. Check ingester logs for errors
2. Verify sentence-transformers installed: `pip list | grep sentence`
3. Check `UploadFile` status in database: should be `ready`, not `failed`

### Issue: Run launch fails with 400/500 error
**Cause:** Invalid directive or missing dependencies  
**Fix:**
1. Ensure migrations applied: `python manage.py migrate`
2. Check API logs: `docker-compose logs web | grep ERROR`
3. Verify directive exists: `curl http://localhost:8000/api/directives/`

### Issue: MCP tests fail
**Cause:** MCP endpoint not configured or SSE format issues  
**Note:** MCP tests are optional and won't fail the entire smoke test. Core RAG functionality is validated independently.

### Issue: "Query privacy guardrail violated"
**Cause:** CRITICAL - Code changed to store query text (security violation)  
**Fix:** 
1. Review recent changes to `RetrievalEvent` model
2. Ensure no `query_text` field exists
3. Verify only `query_hash` is stored
4. Roll back any changes that added query text storage

## Performance Notes
- **Ingestion time:** Typically 5-15 seconds for small files
- **Search latency:** < 2 seconds for small document sets
- **Run execution:** Depends on task implementation (placeholder = instant)

## Security Validation
The smoke test explicitly checks:
1. **No prompt storage:** Job results must not contain `prompt` or `response` keys
2. **Query hashing:** All queries logged via SHA256 hash, never plaintext
3. **Token counts only:** LLM calls (if any) only store `prompt_tokens`, `completion_tokens`, `total_tokens`

If any security check fails, the test exits immediately with non-zero status.

## Integration with CI
This smoke test is designed for:
- Local development validation
- Docker-based CI pipelines
- Pre-merge verification

**CI Example:**
```yaml
# .github/workflows/phase3-smoke.yml
- name: Run Phase 3 Smoke Test
  run: |
    docker-compose up -d
    docker-compose exec -T web python manage.py run_ingester &
    sleep 10
    docker-compose exec -T web /opt/venv/bin/python /app/scripts/smoke_phase3.py
```

## Related Documentation
- [Phase 3 RAG Documentation](PHASE3_RAG.md)
- [API Documentation](../API_DOCS.md)
- [MCP Endpoint Documentation](../mcp/README.md)
- [Security Guardrails](../.github/copilot-instructions.md)
