from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import metrics
from . import schema
from . import rag_views
from . import agent_views

app_name = 'api'

router = DefaultRouter()
router.register(r'directives', views.DirectiveViewSet)
router.register(r'tasks', views.TaskDefinitionViewSet)
router.register(r'runs', views.RunViewSet)
router.register(r'jobs', views.JobViewSet)
router.register(r'containers', views.ContainerAllowlistViewSet)
router.register(r'artifacts', views.RunArtifactViewSet)
router.register(r'schedules', views.ScheduleViewSet)
router.register(r'worker-hosts', views.WorkerHostViewSet, basename='worker-hosts')
router.register(r'rag', rag_views.RAGViewSet, basename='rag')
router.register(r'agent-runs', agent_views.AgentRunViewSet, basename='agent-runs')
router.register(r'repo-plans', views.RepoCopilotViewSet, basename='repo-plans')

urlpatterns = [
    path('', views.index, name='index'),
    # Token accounting and enhanced endpoints (before router to take precedence)
    path('api/token-stats/', views.token_stats, name='token-stats'),
    path('api/cost-report/', views.cost_report, name='cost-report'),
    path('api/usage-by-directive/', views.usage_by_directive, name='usage-by-directive'),
    path('api/runs/since-last-success/', views.runs_since_last_success, name='runs-since-last-success'),
    path('api/container-inventory/', views.container_inventory, name='container-inventory'),
    path('api/schema/', schema.openapi_schema, name='openapi-schema'),
    path('api/docs/', schema.swagger_ui, name='swagger-ui'),
    path('api/redoc/', schema.redoc_ui, name='redoc'),
    # Router for standard REST endpoints
    path('api/', include(router.urls)),
    # Metrics
    path('metrics/', metrics.metrics_view, name='metrics'),
    path('metrics/json/', metrics.metrics_json_view, name='metrics-json'),
]
