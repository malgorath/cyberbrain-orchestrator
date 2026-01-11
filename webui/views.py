from django.shortcuts import render


def schedules(request):
	"""Phase 2: Schedules WebUI page."""
	return render(request, 'webui/schedules.html')


def tasks(request):
	"""TaskDefinitions WebUI page."""
	return render(request, 'webui/tasks.html')


def rag_upload(request):
	"""Phase 3: RAG upload WebUI page."""
	return render(request, 'webui/rag_upload.html')


def rag_search(request):
	"""Phase 3: RAG search WebUI page."""
	return render(request, 'webui/rag_search.html')
