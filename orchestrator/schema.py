"""
OpenAPI Schema Generation

Provides OpenAPI 3.0 schema with Swagger UI for API documentation.
Uses static YAML file in docs/openapi.yaml.
"""

from django.http import HttpResponse, FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
import os


def openapi_schema(request):
    """
    OpenAPI schema endpoint
    GET /api/schema/
    """
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'docs', 'openapi.yaml')
    
    if not os.path.exists(schema_path):
        raise Http404("OpenAPI schema not found")
    
    with open(schema_path, 'r') as f:
        content = f.read()
    
    return HttpResponse(content, content_type='application/x-yaml')


@csrf_exempt
def swagger_ui(request):
    """
    Swagger UI for API documentation
    GET /api/docs/
    """
    return render(request, 'swagger_ui.html')


@csrf_exempt
def redoc_ui(request):
    """
    ReDoc UI for API documentation
    GET /api/redoc/
    """
    return render(request, 'redoc.html')
