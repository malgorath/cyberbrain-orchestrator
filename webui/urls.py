from django.urls import path
from .views import (
	runs, run_detail, directives, worker_hosts, allowlist,
	schedules, tasks, uploads, rag_upload, rag_search
)

urlpatterns = [
	path('runs/', runs, name='webui-runs'),
	path('runs/<int:run_id>/', run_detail, name='webui-run-detail'),
	path('directives/', directives, name='webui-directives'),
	path('worker-hosts/', worker_hosts, name='webui-worker-hosts'),
	path('allowlist/', allowlist, name='webui-allowlist'),
	path('tasks/', tasks, name='webui-tasks'),
	path('schedules/', schedules, name='webui-schedules'),
	path('uploads/', uploads, name='webui-uploads'),
	path('rag/upload/', rag_upload, name='webui-rag-upload'),
	path('rag/search/', rag_search, name='webui-rag-search'),
	path('webui/tasks/', tasks, name='webui-tasks-legacy'),
	path('webui/schedules/', schedules, name='webui-schedules-legacy'),
	path('webui/rag/upload/', rag_upload, name='webui-rag-upload-legacy'),
	path('webui/rag/search/', rag_search, name='webui-rag-search-legacy'),
]
