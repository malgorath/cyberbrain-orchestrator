from django.shortcuts import render


def runs(request):
	"""Runs list WebUI page."""
	return render(request, 'webui/runs.html')


def run_detail(request, run_id):
	"""Run detail WebUI page."""
	return render(request, 'webui/run_detail.html', {'run_id': run_id})


def directives(request):
	"""Directives WebUI page."""
	return render(request, 'webui/directives.html')


def worker_hosts(request):
	"""Worker hosts WebUI page."""
	return render(request, 'webui/worker_hosts.html')


def allowlist(request):
	"""Container allowlist WebUI page."""
	return render(request, 'webui/allowlist.html')


def schedules(request):
	"""Phase 2: Schedules WebUI page."""
	return render(request, 'webui/schedules.html')


def tasks(request):
	"""TaskDefinitions WebUI page."""
	return render(request, 'webui/tasks.html')


def uploads(request):
	"""RAG uploads WebUI page."""
	return render(request, 'webui/rag_upload.html')


def rag_upload(request):
	"""Phase 3: RAG upload WebUI page."""
	return render(request, 'webui/rag_upload.html')


def rag_search(request):
	"""Phase 3: RAG search WebUI page."""
	return render(request, 'webui/rag_search.html')
