"""Minimal MCP SSE endpoint exposing curated tools."""

import json
from typing import Any, Dict, List

from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from core.models import ContainerAllowlist, Directive, Job, Run, RunArtifact
from core.serializers import DirectiveSerializer, RunSerializer

TOOLS: List[Dict[str, Any]] = [
	{"name": "launch_run", "description": "Launch a run for a job/task with directive snapshot"},
	{"name": "list_runs", "description": "List runs with optional status filter"},
	{"name": "get_run", "description": "Get run detail"},
	{"name": "get_run_report", "description": "Get run report markdown + JSON summary"},
	{"name": "list_directives", "description": "List directives"},
	{"name": "get_directive", "description": "Get a directive by id"},
	{"name": "get_allowlist", "description": "List container allowlist entries"},
	{"name": "set_allowlist", "description": "Upsert container allowlist entry"},
	# Phase 3: RAG tools
	{"name": "rag_search", "description": "Search RAG documents with a query (hash-only logging)"},
	{"name": "rag_list_documents", "description": "List ingested documents"},
	{"name": "rag_upload_status", "description": "Get status of uploaded files"},
	# Phase 5: Agent tools
	{"name": "agent_launch", "description": "Launch an autonomous agent run with goal and directive"},
	{"name": "agent_status", "description": "Get current status of an agent run"},
	{"name": "agent_report", "description": "Get final report of a completed agent run"},
	{"name": "agent_cancel", "description": "Cancel an in-progress agent run"},
	# Phase 6: Repo Co-Pilot tools
	{"name": "repo_plan_launch", "description": "Launch a repo copilot plan for a GitHub repository"},
	{"name": "repo_plan_status", "description": "Get status of a repo copilot plan"},
	{"name": "repo_plan_report", "description": "Get final report of a completed repo plan"},
]


def _sse(payload: Dict[str, Any], status: int = 200) -> StreamingHttpResponse:
	data = f"data: {json.dumps(payload)}\n\n"
	return StreamingHttpResponse(iter([data]), content_type="text/event-stream", status=status)


def _error(message: str, status: int = 400) -> StreamingHttpResponse:
	return _sse({"error": message}, status=status)


def _resolve_job(job_id: Any = None, task_key: str = None) -> Job:
	if job_id is not None:
		return Job.objects.get(id=job_id)
	if task_key is not None:
		return Job.objects.get(task_key=task_key)
	raise Job.DoesNotExist("job_id or task_key required")


def _snapshot_directive(directive_id: Any = None, custom_text: str = None) -> Dict[str, str]:
	if directive_id is not None:
		directive = Directive.objects.get(id=directive_id)
		return {"name": directive.name, "text": directive.directive_text or ''}
	if custom_text:
		return {"name": "custom", "text": custom_text}
	return {"name": "default", "text": ""}


def _serialize_runs(qs):
	return RunSerializer(qs, many=True).data


def _serialize_run(run: Run):
	return RunSerializer(run).data


@csrf_exempt
def mcp_endpoint(request):
	"""Minimal MCP endpoint using Streamable HTTP + SSE style responses."""
	if request.method == 'GET':
		return JsonResponse({
			"transport": "sse",
			"endpoint": "/mcp",
			"tools": TOOLS,
		})

	try:
		payload = json.loads(request.body.decode('utf-8') or '{}')
	except json.JSONDecodeError:
		return _error("Invalid JSON payload", status=400)

	tool = payload.get('tool')
	params = payload.get('params', {})

	if tool == 'launch_run':
		try:
			job = _resolve_job(params.get('job_id'), params.get('task_key'))
		except Job.DoesNotExist:
			return _error("job_id or task_key not found", status=404)

		try:
			snapshot = _snapshot_directive(params.get('directive_id'), params.get('custom_directive_text'))
		except Directive.DoesNotExist:
			return _error("directive_id not found", status=404)

		run = Run.objects.create(
			job=job,
			directive_snapshot_name=snapshot["name"],
			directive_snapshot_text=snapshot["text"],
			status='pending',
			started_at=timezone.now(),
			report_markdown="Run created",
			report_json={"status": "pending"},
			report_markdown_path=params.get('report_markdown_path', ''),
			report_json_path=params.get('report_json_path', ''),
			output_path=params.get('output_path', ''),
		)

		RunArtifact.objects.create(
			run=run,
			artifact_type='markdown',
			path=run.report_markdown_path or f"runs/{run.id}/report.md",
			file_size_bytes=0,
		)

		return _sse({"ok": True, "run": _serialize_run(run)})

	if tool == 'list_runs':
		qs = Run.objects.all().order_by('-started_at')
		status_filter = params.get('status')
		if status_filter:
			qs = qs.filter(status=status_filter)
		return _sse({"runs": _serialize_runs(qs)})

	if tool == 'get_run':
		try:
			run = Run.objects.get(id=params.get('run_id'))
		except Run.DoesNotExist:
			return _error("run not found", status=404)
		return _sse({"run": _serialize_run(run)})

	if tool == 'get_run_report':
		try:
			run = Run.objects.get(id=params.get('run_id'))
		except Run.DoesNotExist:
			return _error("run not found", status=404)
		return _sse({
			"run_id": run.id,
			"markdown": run.report_markdown,
			"summary": run.report_json,
			"total_tokens": run.token_total,
		})

	if tool == 'list_directives':
		directives = Directive.objects.all().order_by('directive_type', 'name')
		return _sse({"directives": DirectiveSerializer(directives, many=True).data})

	if tool == 'get_directive':
		try:
			directive = Directive.objects.get(id=params.get('directive_id'))
		except Directive.DoesNotExist:
			return _error("directive not found", status=404)
		return _sse({"directive": DirectiveSerializer(directive).data})

	if tool == 'get_allowlist':
		entries = ContainerAllowlist.objects.filter(enabled=True).order_by('container_name')
		return _sse({"allowlist": list(entries.values('container_id', 'container_name', 'enabled'))})

	if tool == 'set_allowlist':
		container_id = params.get('container_id')
		container_name = params.get('container_name', '')
		if not container_id:
			return _error("container_id required", status=400)
		entry, _ = ContainerAllowlist.objects.update_or_create(
			container_id=container_id,
			defaults={"container_name": container_name, "enabled": params.get('enabled', True)}
		)
		return _sse({
			"allowlist": {
				"container_id": entry.container_id,
				"container_name": entry.container_name,
				"enabled": entry.enabled,
			}
		})

	# Phase 3: RAG tools
	if tool == 'rag_search':
		"""
		Search RAG documents with a query.
		
		SECURITY GUARDRAIL: Query is hashed for logging, not stored as plaintext.
		"""
		from core.models import Embedding, RetrievalEvent, Document
		from core.management.commands.run_ingester import EmbeddingService
		from orchestrator.rag_views import cosine_similarity, compute_query_hash
		import hashlib
		
		query_text = params.get('query_text', '').strip()
		top_k = params.get('top_k', 5)
		
		if not query_text:
			return _error("query_text required", status=400)
		
		try:
			# Generate query hash (no plaintext storage)
			query_hash = compute_query_hash(query_text)
			
			# Generate query embedding
			embedding_service = EmbeddingService()
			query_embedding = embedding_service.embed([query_text])[0]
			
			# Find similar chunks
			embeddings = Embedding.objects.select_related('chunk__document').all()
			scored_chunks = []
			for emb in embeddings:
				score = cosine_similarity(query_embedding, emb.vector)
				scored_chunks.append({
					'chunk_id': emb.chunk.id,
					'chunk_text': emb.chunk.text,
					'chunk_index': emb.chunk.chunk_index,
					'document_id': emb.chunk.document.id,
					'document_title': emb.chunk.document.title,
					'document_source': emb.chunk.document.source,
					'score': score
				})
			
			# Sort and take top-k
			scored_chunks.sort(key=lambda x: x['score'], reverse=True)
			results = scored_chunks[:top_k]
			
			# Log retrieval event (hash only)
			RetrievalEvent.objects.create(
				run=None,  # MCP calls don't have a run context
				query_hash=query_hash,
				top_k=top_k,
				results_count=len(results)
			)
			
			return _sse({
				"query_hash": query_hash,
				"results": results,
				"total_found": len(results)
			})
		except Exception as e:
			return _error(f"RAG search failed: {str(e)}", status=500)

	if tool == 'rag_list_documents':
		"""List ingested documents."""
		from core.models import Document
		
		docs = Document.objects.all().order_by('-created_at')
		
		# Optional filters
		upload_id = params.get('upload_id')
		if upload_id:
			docs = docs.filter(upload_id=upload_id)
		
		doc_list = []
		for doc in docs[:100]:  # Limit to 100
			doc_list.append({
				'id': doc.id,
				'title': doc.title,
				'source': doc.source,
				'upload_id': doc.upload_id,
				'created_at': doc.created_at.isoformat(),
				'chunk_count': doc.chunks.count()
			})
		
		return _sse({"documents": doc_list, "count": len(doc_list)})

	if tool == 'rag_upload_status':
		"""Get status of uploaded files."""
		from core.models import UploadFile
		
		uploads = UploadFile.objects.all().order_by('-uploaded_at')
		
		# Optional filters
		status_filter = params.get('status')
		if status_filter:
			uploads = uploads.filter(status=status_filter)
		
		upload_list = []
		for upload in uploads[:100]:  # Limit to 100
			upload_list.append({
				'id': upload.id,
				'filename': upload.filename,
				'size_bytes': upload.size_bytes,
				'mime_type': upload.mime_type,
				'status': upload.status,
				'uploaded_at': upload.uploaded_at.isoformat(),
				'processed_at': upload.processed_at.isoformat() if upload.processed_at else None,
				'error_message': upload.error_message,
				'document_count': upload.documents.count()
			})
		
		return _sse({"uploads": upload_list, "count": len(upload_list)})

	# Phase 5: Agent tools
	if tool == 'agent_launch':
		"""Launch an autonomous agent run."""
		from core.models import AgentRun, AgentStep
		from orchestrator.agent.planner import PlannerService
		from orchestrator.agent.executor import AgentExecutor
		
		goal = params.get('goal')
		directive_id = params.get('directive_id')
		budgets = params.get('budgets', {})
		
		if not goal:
			return _error("goal is required", status=400)
		
		# Get directive
		if directive_id:
			try:
				directive = Directive.objects.get(id=directive_id)
			except Directive.DoesNotExist:
				return _error(f"Directive {directive_id} not found", status=400)
		else:
			directive = Directive.objects.filter(is_active=True).first()
			if not directive:
				return _error("No active directive found", status=400)
		
		# Generate plan
		try:
			planner = PlannerService()
			plan = planner.plan(goal, directive)
		except Exception as e:
			return _error(f"Plan generation failed: {str(e)}", status=400)
		
		# Create agent run
		max_steps = budgets.get('max_steps', 10)
		time_budget_minutes = budgets.get('time_minutes', 60)
		token_budget = budgets.get('tokens', 10000)
		
		initial_status = 'pending_approval' if directive.approval_required else 'pending'
		
		agent_run = AgentRun.objects.create(
			operator_goal=goal,
			directive_snapshot=directive.to_json(),
			status=initial_status,
			max_steps=max_steps,
			time_budget_minutes=time_budget_minutes,
			token_budget=token_budget,
		)
		
		# Create steps from plan
		for step_data in plan:
			AgentStep.objects.create(
				agent_run=agent_run,
				step_index=step_data.get('step_index', 0),
				step_type=step_data.get('step_type', 'task_call'),
				task_id=step_data.get('task_id', ''),
				inputs=step_data.get('inputs', {}),
				status='pending',
			)
		
		# Execute if not approval-gated
		if initial_status != 'pending_approval':
			executor = AgentExecutor()
			try:
				executor.execute(agent_run)
			except Exception as e:
				agent_run.status = 'failed'
				agent_run.error_message = str(e)
				agent_run.save()
		
		return _sse({
			'agent_run_id': agent_run.id,
			'status': agent_run.status,
			'plan': plan,
		})
	
	if tool == 'agent_status':
		"""Get status of an agent run."""
		from core.models import AgentRun
		
		agent_run_id = params.get('agent_run_id')
		if not agent_run_id:
			return _error("agent_run_id is required", status=400)
		
		try:
			agent_run = AgentRun.objects.get(id=agent_run_id)
		except AgentRun.DoesNotExist:
			return _error(f"Agent run {agent_run_id} not found", status=404)
		
		return _sse({
			'agent_run_id': agent_run.id,
			'status': agent_run.status,
			'current_step': agent_run.current_step,
			'max_steps': agent_run.max_steps,
			'tokens_used': agent_run.tokens_used,
			'token_budget': agent_run.token_budget,
		})
	
	if tool == 'agent_report':
		"""Get final report of an agent run."""
		from core.models import AgentRun
		
		agent_run_id = params.get('agent_run_id')
		if not agent_run_id:
			return _error("agent_run_id is required", status=400)
		
		try:
			agent_run = AgentRun.objects.get(id=agent_run_id)
		except AgentRun.DoesNotExist:
			return _error(f"Agent run {agent_run_id} not found", status=404)
		
		# Build steps summary
		steps_summary = []
		for step in agent_run.steps.all().order_by('step_index'):
			steps_summary.append({
				'step_index': step.step_index,
				'task_id': step.task_id,
				'status': step.status,
				'duration_seconds': step.duration_seconds(),
				'error': step.error_message if step.status == 'failed' else None,
			})
		
		report = {
			'agent_run_id': agent_run.id,
			'operator_goal': agent_run.operator_goal,
			'status': agent_run.status,
			'total_steps': len(steps_summary),
			'successful_steps': sum(1 for s in steps_summary if s['status'] == 'success'),
			'failed_steps': sum(1 for s in steps_summary if s['status'] == 'failed'),
			'tokens_used': agent_run.tokens_used,
			'time_elapsed_minutes': agent_run.time_elapsed_minutes(),
			'steps': steps_summary,
		}
		
		return _sse({'summary': report, 'json': agent_run.report_json})
	
	if tool == 'agent_cancel':
		"""Cancel an agent run."""
		from core.models import AgentRun
		
		agent_run_id = params.get('agent_run_id')
		if not agent_run_id:
			return _error("agent_run_id is required", status=400)
		
		try:
			agent_run = AgentRun.objects.get(id=agent_run_id)
		except AgentRun.DoesNotExist:
			return _error(f"Agent run {agent_run_id} not found", status=404)
		
		if agent_run.status in ['completed', 'failed', 'cancelled']:
			return _error(f"Cannot cancel agent run with status {agent_run.status}", status=400)
		
		agent_run.status = 'cancelled'
		agent_run.ended_at = timezone.now()
		agent_run.save()
		
		return _sse({'agent_run_id': agent_run.id, 'status': 'cancelled'})

	if tool == 'repo_plan_launch':
		"""Launch a repo copilot plan."""
		from core.models import RepoCopilotPlan, Directive as CoreDirective
		from orchestrator.services import RepoCopilotService
		
		repo_url = params.get('repo_url')
		base_branch = params.get('base_branch')
		goal = params.get('goal')
		directive_id = params.get('directive_id')
		create_branch_flag = params.get('create_branch_flag', False)
		push_flag = params.get('push_flag', False)
		
		if not all([repo_url, base_branch, goal, directive_id]):
			return _error("repo_url, base_branch, goal, and directive_id are required", status=400)
		
		try:
			directive = CoreDirective.objects.get(id=directive_id)
		except CoreDirective.DoesNotExist:
			return _error("Directive not found", status=404)
		
		# Validate directive gating
		service = RepoCopilotService()
		flags = {'create_branch_flag': create_branch_flag, 'push_flag': push_flag}
		
		try:
			gating_result = service.validate_directive_gating(directive, flags)
		except ValueError as e:
			return _sse({'error': str(e)}, status=403)
		
		# Create repo plan
		try:
			plan_obj = RepoCopilotPlan.objects.create(
				repo_url=repo_url,
				base_branch=base_branch,
				goal=goal,
				directive=directive,
				directive_snapshot=directive.to_json() if hasattr(directive, 'to_json') else {},
				status='pending',
			)
			
			plan_obj.status = 'generating'
			plan_obj.started_at = timezone.now()
			plan_obj.save()
			
			plan = service.generate_plan(repo_url, base_branch, goal, directive)
			
			plan_obj.plan = plan
			plan_obj.status = 'success'
			plan_obj.completed_at = timezone.now()
			plan_obj.save()
			
			return _sse({
				'repo_plan_id': plan_obj.id,
				'status': plan_obj.status,
				'plan': plan,
				'created_at': plan_obj.created_at.isoformat(),
			})
		
		except Exception as e:
			if 'plan_obj' in locals():
				plan_obj.status = 'failed'
				plan_obj.error_message = str(e)
				plan_obj.completed_at = timezone.now()
				plan_obj.save()
			
			return _sse({'error': f'Failed to generate plan: {str(e)}'}, status=500)

	if tool == 'repo_plan_status':
		"""Get status of a repo copilot plan."""
		from core.models import RepoCopilotPlan
		
		repo_plan_id = params.get('repo_plan_id')
		if not repo_plan_id:
			return _error("repo_plan_id is required", status=400)
		
		try:
			plan_obj = RepoCopilotPlan.objects.get(id=repo_plan_id)
		except RepoCopilotPlan.DoesNotExist:
			return _error(f"Plan {repo_plan_id} not found", status=404)
		
		return _sse({
			'repo_plan_id': plan_obj.id,
			'status': plan_obj.status,
			'created_at': plan_obj.created_at.isoformat(),
			'completed_at': plan_obj.completed_at.isoformat() if plan_obj.completed_at else None,
			'duration_seconds': plan_obj.duration_seconds(),
		})

	if tool == 'repo_plan_report':
		"""Get report of a repo copilot plan."""
		from core.models import RepoCopilotPlan
		
		repo_plan_id = params.get('repo_plan_id')
		if not repo_plan_id:
			return _error("repo_plan_id is required", status=400)
		
		try:
			plan_obj = RepoCopilotPlan.objects.get(id=repo_plan_id)
		except RepoCopilotPlan.DoesNotExist:
			return _error(f"Plan {repo_plan_id} not found", status=404)
		
		if plan_obj.status == 'failed':
			return _sse({
				'repo_plan_id': plan_obj.id,
				'status': plan_obj.status,
				'error_message': plan_obj.error_message,
			})
		
		return _sse({
			'repo_plan_id': plan_obj.id,
			'status': plan_obj.status,
			'summary': f"Plan for {plan_obj.repo_url}@{plan_obj.base_branch}",
			'markdown': plan_obj.plan.get('markdown', '') if plan_obj.plan else '',
			'plan_json': plan_obj.plan if plan_obj.plan else {},
			'created_at': plan_obj.created_at.isoformat(),
			'completed_at': plan_obj.completed_at.isoformat() if plan_obj.completed_at else None,
		})

	return _error("unknown tool", status=400)
