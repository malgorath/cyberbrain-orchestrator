from django.urls import path
from .views import schedules, tasks, rag_upload, rag_search

urlpatterns = [
    path('webui/tasks/', tasks, name='webui-tasks'),
    path('webui/schedules/', schedules, name='webui-schedules'),
    path('webui/rag/upload/', rag_upload, name='webui-rag-upload'),
    path('webui/rag/search/', rag_search, name='webui-rag-search'),
]
