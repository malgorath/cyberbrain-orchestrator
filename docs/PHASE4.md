# Phase 4: Autonomy + Notifications + Auth

## Overview

Phase 4 adds operational maturity features:
- **Notifications**: Discord/email alerts for run completion
- **Approval Gating**: D3/D4 directive runs require approval before execution
- **Network Policies**: Task 3 generates K8s NetworkPolicy recommendations
- **Auth Framework**: Optional authentication (deferred full implementation)

**Security Guardrails Maintained:**
- Local-only LLMs
- Token counts only (no prompt/response storage)
- Notification payloads are counts-only
- All existing guardrails preserved

## Status

**Completed:**
- Models and migrations
- Notification service (Discord webhooks, email)
- Approval status fields on Run model
- NetworkPolicyRecommendation model
- Acceptance tests

**Deferred (Future Phases):**
- WebUI for notification management
- WebUI for approval workflow
- MCP tool enforcement of approval status
- Full auth implementation (AUTH_ENABLED flag)
- Task 3 integration for automatic policy generation

## Models

### NotificationTarget (core/models.py)

Configures notification destinations.

Fields:
- `name`: Human-readable name
- `type`: discord | email
- `enabled`: Boolean
- `config`: JSON with type-specific configuration

Example:
```python
NotificationTarget.objects.create(
    name='ops-discord',
    type='discord',
    enabled=True,
    config={'webhook_url': 'https://discord.com/api/webhooks/...'}
)
```

### RunNotification (core/models.py)

Tracks notification delivery.

Fields:
- `run`: FK to orchestrator.Run
- `target`: FK to NotificationTarget
- `status`: pending | sent | failed
- `sent_at`: Timestamp
- `error_summary`: Failure reason if status=failed

**SECURITY GUARDRAIL**: Notification payloads contain counts only, no LLM content.

### Run.approval_status (orchestrator/models.py)

Added fields for approval workflow:
- `approval_status`: none | pending | approved | denied
- `approved_by`: Username/identifier
- `approved_at`: Timestamp

Usage:
```python
run = Run.objects.create(
    directive=d3_directive,
    approval_status='pending'  # Requires approval before execution
)

# Later, approve:
run.approval_status = 'approved'
run.approved_by = 'admin_user'
run.approved_at = timezone.now()
run.save()
```

### NetworkPolicyRecommendation (core/models.py)

Stores K8s NetworkPolicy recommendations from Task 3.

Fields:
- `run`: FK to orchestrator.Run
- `source_service`: Service name
- `target_service`: Service name
- `port`: Port number
- `protocol`: tcp | udp
- `recommendation`: Human-readable description
- `policy_yaml`: Generated K8s YAML

Example:
```python
NetworkPolicyRecommendation.objects.create(
    run=run,
    source_service='web',
    target_service='api',
    port=8080,
    protocol='tcp',
    recommendation='Allow web → api on port 8080/tcp',
    policy_yaml='apiVersion: networking.k8s.io/v1...'
)
```

## Notification Service

### Sending Notifications

```python
from core.notifications import NotificationService

# Automatically send to all enabled targets
NotificationService.send_run_notification(run)
```

### Test Notification

```python
target = NotificationTarget.objects.get(name='ops-discord')
success, message = NotificationService.test_notification(target)
```

### Discord Webhook Payload

Embeds are counts-only:
```json
{
  "embeds": [{
    "title": "Run #123 - COMPLETED",
    "description": "Directive: D1 - Log Triage",
    "color": 3066993,
    "fields": [
      {"name": "Status", "value": "completed"},
      {"name": "Jobs", "value": "3/3 completed"},
      {"name": "LLM Tokens", "value": "1250"}
    ]
  }]
}
```

**NO** prompt/response content is included.

### Email Payload

Plain text, counts-only:
```
Run #123 has completed with status: completed

Directive: D1 - Log Triage
Status: completed
Jobs: 3/3 completed
LLM Tokens: 1250

---
Cyberbrain Orchestrator
```

## Approval Gating

### Directives Requiring Approval

D3 and D4 directives require approval before execution:
- **D3 - Code Write**: Write code to local files
- **D4 - Repo Write**: Push changes to repositories

### Workflow

1. **Create Run**: Set `approval_status='pending'`
```python
run = Run.objects.create(
    directive=d3_directive,
    approval_status='pending'
)
```

2. **Check Before Execution**:
```python
if run.approval_status != 'approved':
    raise PermissionError("Run requires approval")
```

3. **Approve**:
```python
run.approval_status = 'approved'
run.approved_by = 'admin_user'
run.approved_at = timezone.now()
run.save()
```

4. **Execute**: Orchestrator service proceeds

### MCP Tool Enforcement (Future)

MCP tools will check approval status before destructive operations:
```python
if run.approval_status != 'approved':
    return {"error": "Operation requires approval"}
```

## Network Policy Recommendations

### Task 3 Integration (Future)

Task 3 (service mapping) will generate NetworkPolicy recommendations:

1. Analyze Docker container network connections
2. Generate K8s NetworkPolicy YAML
3. Store as NetworkPolicyRecommendation

### Manual Creation

```python
policy = NetworkPolicyRecommendation.objects.create(
    run=run,
    source_service='web',
    target_service='database',
    port=5432,
    protocol='tcp',
    recommendation='Allow web service to access database on port 5432',
    policy_yaml="""
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-web-to-db
spec:
  podSelector:
    matchLabels:
      app: database
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: web
    ports:
    - protocol: TCP
      port: 5432
"""
)
```

### Querying Policies

```python
# Get all policies for a run
policies = NetworkPolicyRecommendation.objects.filter(run=run)

# Get policies by service
web_policies = NetworkPolicyRecommendation.objects.filter(
    source_service='web'
)
```

## Auth Framework (Deferred)

### Design

- **ENV Flag**: `AUTH_ENABLED=true` activates auth
- **WebUI**: Session auth (Django built-in)
- **API**: Token auth (DRF TokenAuthentication)
- **Roles**: admin | operator (minimal RBAC)

### When AUTH_ENABLED=false (Default)

- AllowAny permissions remain
- No login required
- Current behavior preserved

### When AUTH_ENABLED=true (Future)

- WebUI requires login
- API requires token in `Authorization: Token <token>` header
- Approval actions restricted to admin role

## Testing

Run acceptance tests:
```bash
python manage.py test tests.acceptance.test_phase4 --settings=cyberbrain_orchestrator.test_settings
```

Tests verify:
1. NotificationTarget and RunNotification models work
2. Notification payloads are counts-only (no LLM content)
3. Approval status workflow
4. NetworkPolicyRecommendation storage
5. Guardrail compliance (no prompt/response fields)

## Security Guardrails

### Notification Payloads

**CORRECT:**
```python
payload = {
    "jobs_completed": 3,
    "total_tokens": 1250,
    "status": "completed"
}
```

**WRONG:**
```python
# ❌ PROHIBITED
payload = {
    "llm_prompt": "...",  # Never include
    "llm_response": "..."  # Never include
}
```

### RunNotification Model

```python
class RunNotification(models.Model):
    run = models.ForeignKey(...)
    target = models.ForeignKey(...)
    status = models.CharField(...)
    # WARNING: Do NOT add prompt/response fields
```

### Approval Workflow

Approval status does not store or transmit LLM content:
- Only metadata: approver name, timestamp, status
- Execution still uses token-only logging

## Migrations

Generated migrations:
- `orchestrator/migrations/0002_run_approval_status_run_approved_at_run_approved_by.py`
- `core/migrations/0006_notificationtarget_networkpolicyrecommendation_and_more.py`

Apply:
```bash
python manage.py migrate
```

## Dependencies

No new dependencies required. Uses standard library and existing packages:
- `requests` (already installed) - for Discord webhooks
- `django.core.mail` (built-in) - for email

## Future Enhancements

1. **WebUI Pages**:
   - `/webui/notifications` - Manage targets, view history
   - `/webui/approvals` - Approve/deny pending runs

2. **MCP Integration**:
   - `approve_run(run_id)` tool
   - `list_pending_approvals()` tool
   - Enforce approval checks in write tools

3. **Auth Implementation**:
   - User model and login views
   - Token generation API
   - Role-based permissions

4. **Task 3 Auto-generation**:
   - Detect network connections during service mapping
   - Generate NetworkPolicy YAML automatically
   - Propose least-privilege policies

## References

- Models: [core/models.py](../core/models.py) (Phase 4 section)
- Notification Service: [core/notifications.py](../core/notifications.py)
- Tests: [tests/acceptance/test_phase4.py](../tests/acceptance/test_phase4.py)
- Migrations:
  - [orchestrator/migrations/0002_*.py](../orchestrator/migrations/)
  - [core/migrations/0006_*.py](../core/migrations/)
