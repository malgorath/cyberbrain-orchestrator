# Changelog

All notable changes to Cyberbrain Orchestrator are documented in this file.

## [Phase 7] - 2026-01-09

### Added
- **Multi-Host Worker Expansion**
  - WorkerHost model with `docker_socket` and `docker_tcp` types for local and remote host support
  - HostRouter with intelligent host selection using load balancing and GPU-aware routing
  - HealthChecker service with Docker daemon health monitoring and staleness detection
  - SSHTunnelManager framework for secure SSH-tunneled Docker access to remote VMs
  - WorkerHostViewSet API endpoints (CRUD + health status) at `/api/worker-hosts/`
  - Extended `RunViewSet.launch()` to accept `target_host_id` for explicit host selection

### Changed
- Extended Run model to track assigned worker_host
- Extended ContainerInventory to track per-host container snapshots
- Updated LaunchRunSerializer to support target_host_id parameter

### Security
- SSH credentials protected in JSONField, never exposed in logs or API responses
- LAN-only IP constraint enforced for WorkerHost addresses
- All security guardrails from previous phases maintained (no LLM content storage, token counts only)

### Testing
- Added 27 comprehensive acceptance tests in `tests/acceptance/test_multi_host.py`
- Test coverage: 25/27 passing, 2 skipped (awaiting paramiko library for SSH tunnels)
- All Phase 5 (17/17) and Phase 6 (20/20) tests passing - no regressions
- Django system check: 0 issues

### Migrations
- `core/migrations/0010_workerhost_containerinventory_worker_host.py` - New WorkerHost table and FK updates
- `orchestrator/migrations/0004_run_worker_host_alter_job_task_type.py` - Run.worker_host FK

---

## [Phase 6] - Previous

### Summary
Repo Copilot Option B MVP - AI-powered GitHub repository analysis and planning

---

## [Phase 5] - Previous

### Summary
Cyber-Brain Agent Runtime - Multi-step agent orchestration with LLM integration

---

## [Phase 1-4] - Previous

### Summary
Foundation phases covering core orchestration, RAG, MCP control plane, and worker orchestration

---

## Development Notes

### For Phase 8 (Optional Enhancements)
- Implement paramiko library integration to complete SSH tunnel support (un-skip 2 tests)
- Add default Unraid WorkerHost creation during setup
- Implement advanced routing features (task affinity, resource monitoring)
- Add high-availability features (automatic retry, run reassignment)

### Deployment Checklist
- [ ] Apply migrations: `python manage.py migrate`
- [ ] Create default Unraid host via API or Django admin
- [ ] Configure VM host if using multi-host setup
- [ ] Verify health checks with `GET /api/worker-hosts/{id}/health/?check=true`
- [ ] Test run launch: `POST /api/runs/launch/ {"tasks": ["log_triage"]}`

---

## Repository Statistics

- **Total Tests**: 64 (62 passing, 2 skipped)
- **Test Coverage**: ATDD-driven development with acceptance tests
- **Code Quality**: Follows Conventional Commit messages and ATDD+DbC patterns
- **CI Gates**: validate.py, Django tests, system checks passing
