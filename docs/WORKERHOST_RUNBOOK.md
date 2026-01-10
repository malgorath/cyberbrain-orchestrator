# WorkerHost Operations Runbook

## Register a Worker Host

### Via API

**Local Docker Socket (Unraid):**
```bash
curl -X POST http://localhost:9595/api/worker-hosts/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Unraid",
    "type": "docker_socket",
    "base_url": "unix:///var/run/docker.sock",
    "enabled": true,
    "capabilities": {
      "gpus": true,
      "gpu_count": 2,
      "max_concurrency": 5
    }
  }'
```

**Remote Docker TCP (VM):**
```bash
curl -X POST http://localhost:9595/api/worker-hosts/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "VM-192.168.1.15",
    "type": "docker_tcp",
    "base_url": "tcp://192.168.1.15:2376",
    "enabled": true,
    "capabilities": {
      "gpus": false,
      "max_concurrency": 3
    },
    "ssh_config": {
      "host": "192.168.1.15",
      "port": 22,
      "user": "vmadmin",
      "key_path": "/secrets/vm_ssh_key"
    }
  }'
```

## Verify Health and Heartbeat

The `/health/` endpoint updates `last_seen_at` to prevent hosts from becoming stale:

```bash
# Get health status (updates last_seen_at automatically)
curl http://localhost:9595/api/worker-hosts/1/health/

# Response should show:
# {
#   "host_id": 1,
#   "name": "Unraid",
#   "healthy": true,
#   "last_seen_at": "2026-01-10T12:34:56Z",  # <-- Should be recent
#   "is_stale": false,                       # <-- Should be false
#   "active_runs_count": 0
# }
```

**Trigger Docker Health Check:**
```bash
curl http://localhost:9595/api/worker-hosts/1/health/?check=true
```

## Launch a Run

Runs require a directive ID:

```bash
# Launch with default task selection
curl -X POST http://localhost:9595/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{
    "directive_id": 1
  }'

# Launch specific tasks
curl -X POST http://localhost:9595/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{
    "directive_id": 1,
    "tasks": ["log_triage", "gpu_report"]
  }'

# Launch on specific host
curl -X POST http://localhost:9595/api/runs/launch/ \
  -H "Content-Type: application/json" \
  -d '{
    "directive_id": 1,
    "tasks": ["log_triage"],
    "target_host_id": 2
  }'
```

## Create a Directive

If no directive exists:

```bash
curl -X POST http://localhost:9595/api/directives/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "default",
    "description": "Default orchestrator directive"
  }'
```

## Troubleshooting

### "No available hosts found"

Check host status:
```bash
curl http://localhost:9595/api/worker-hosts/
```

Verify:
- `enabled: true`
- `healthy: true`
- `last_seen_at` is recent (not null, not older than 5 minutes)
- `is_stale: false`

**Fix stale hosts:**
```bash
# Access health endpoint to update heartbeat
curl http://localhost:9595/api/worker-hosts/1/health/
```

### Host shows as stale

The `last_seen_at` field must be updated regularly. Access the health endpoint:

```bash
curl http://localhost:9595/api/worker-hosts/1/health/
```

Set up a cron job or monitoring script to ping the health endpoint every 2-3 minutes.

### Host marked unhealthy

Trigger a health check:
```bash
curl http://localhost:9595/api/worker-hosts/1/health/?check=true
```

Verify Docker daemon is accessible:
- For `docker_socket`: Check socket permissions
- For `docker_tcp`: Check network connectivity and firewall

## Monitoring

List all hosts:
```bash
curl http://localhost:9595/api/worker-hosts/ | jq .
```

Check specific host:
```bash
curl http://localhost:9595/api/worker-hosts/1/ | jq .
```

View active runs:
```bash
curl http://localhost:9595/api/runs/?status=running | jq .
```
