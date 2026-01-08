from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'directives', views.DirectiveViewSet)
router.register(r'runs', views.RunViewSet)
router.register(r'jobs', views.JobViewSet)
router.register(r'containers', views.ContainerAllowlistViewSet)

urlpatterns = [
    path('', views.index, name='index'),
    path('api/', include(router.urls)),
]
