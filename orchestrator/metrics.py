"""
Observability: Lightweight Metrics System

Provides metrics for:
- Run creation/completion rates
- Job execution times
- LLM token usage
- API request rates

No external dependencies - uses Django cache for storage.
Compatible with Prometheus via simple text format.
"""

from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.http import require_GET
from functools import wraps
from collections import defaultdict
import time
import json


# Metrics storage keys
METRICS_KEY_PREFIX = 'cyberbrain_metrics_'
METRICS_COUNTERS = f'{METRICS_KEY_PREFIX}counters'
METRICS_HISTOGRAMS = f'{METRICS_KEY_PREFIX}histograms'
METRICS_GAUGES = f'{METRICS_KEY_PREFIX}gauges'


def _get_counters():
    """Get all counters from cache"""
    return cache.get(METRICS_COUNTERS) or defaultdict(int)


def _get_histograms():
    """Get all histograms from cache"""
    return cache.get(METRICS_HISTOGRAMS) or defaultdict(list)


def _get_gauges():
    """Get all gauges from cache"""
    return cache.get(METRICS_GAUGES) or {}


def _save_counters(counters):
    """Save counters to cache"""
    cache.set(METRICS_COUNTERS, dict(counters), timeout=None)


def _save_histograms(histograms):
    """Save histograms to cache"""
    cache.set(METRICS_HISTOGRAMS, dict(histograms), timeout=None)


def _save_gauges(gauges):
    """Save gauges to cache"""
    cache.set(METRICS_GAUGES, gauges, timeout=None)


def _increment_counter(name, labels=None, amount=1):
    """Increment a counter metric"""
    counters = _get_counters()
    key = f"{name}{json.dumps(labels or {}, sort_keys=True)}"
    if key not in counters:
        counters[key] = 0
    counters[key] += amount
    _save_counters(counters)


def _observe_histogram(name, value, labels=None):
    """Record a histogram observation"""
    histograms = _get_histograms()
    key = f"{name}{json.dumps(labels or {}, sort_keys=True)}"
    histograms[key].append(value)
    # Keep only last 1000 observations
    if len(histograms[key]) > 1000:
        histograms[key] = histograms[key][-1000:]
    _save_histograms(histograms)


def _set_gauge(name, value, labels=None):
    """Set a gauge metric"""
    gauges = _get_gauges()
    key = f"{name}{json.dumps(labels or {}, sort_keys=True)}"
    gauges[key] = value
    _save_gauges(gauges)


# Metric recording functions
def record_run_created(status='pending'):
    """Record a run creation"""
    _increment_counter('runs_created_total', {'status': status})


def record_run_completed(status):
    """Record a run completion"""
    _increment_counter('runs_completed_total', {'status': status})


def record_job_created(task_key):
    """Record a job creation"""
    _increment_counter('jobs_created_total', {'task_key': task_key})


def record_job_duration(task_key, status, duration_seconds):
    """Record job execution duration"""
    _observe_histogram('jobs_duration_seconds', duration_seconds, {'task_key': task_key, 'status': status})


def record_llm_tokens(model_id, prompt_tokens=0, completion_tokens=0, total_tokens=0):
    """Record LLM token usage"""
    if prompt_tokens > 0:
        _increment_counter('llm_tokens_total', {'model_id': model_id, 'token_type': 'prompt'}, prompt_tokens)
    if completion_tokens > 0:
        _increment_counter('llm_tokens_total', {'model_id': model_id, 'token_type': 'completion'}, completion_tokens)
    if total_tokens > 0:
        _increment_counter('llm_tokens_total', {'model_id': model_id, 'token_type': 'total'}, total_tokens)


def record_llm_call(model_id, endpoint):
    """Record an LLM API call"""
    _increment_counter('llm_calls_total', {'model_id': model_id, 'endpoint': endpoint})


def record_api_request(method, endpoint, status):
    """Record an API request"""
    _increment_counter('api_requests_total', {'method': method, 'endpoint': endpoint, 'status': str(status)})


def update_active_runs_gauge(count):
    """Update the active runs gauge"""
    _set_gauge('active_runs', count)


# Decorator for tracking API request duration
def track_api_duration(endpoint_name):
    """Decorator to track API request duration"""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            start_time = time.time()
            response = func(request, *args, **kwargs)
            duration = time.time() - start_time
            
            method = request.method
            status = response.status_code
            
            _observe_histogram('api_request_duration_seconds', duration, {
                'method': method,
                'endpoint': endpoint_name
            })
            
            record_api_request(method, endpoint_name, status)
            
            return response
        return wrapper
    return decorator


def reset_metrics():
    """Reset all metrics (for testing)"""
    cache.delete(METRICS_COUNTERS)
    cache.delete(METRICS_HISTOGRAMS)
    cache.delete(METRICS_GAUGES)


@require_GET
def metrics_view(request):
    """
    Metrics endpoint in Prometheus text format
    GET /metrics/
    """
    lines = []
    
    # Counters
    counters = _get_counters()
    for key, value in counters.items():
        lines.append(f"{key} {value}")
    
    # Gauges
    gauges = _get_gauges()
    for key, value in gauges.items():
        lines.append(f"{key} {value}")
    
    # Histograms (simplified: count, sum, min, max, avg)
    histograms = _get_histograms()
    for key, values in histograms.items():
        if values:
            count = len(values)
            total = sum(values)
            avg = total / count
            lines.append(f"{key}_count {count}")
            lines.append(f"{key}_sum {total:.6f}")
            lines.append(f"{key}_min {min(values):.6f}")
            lines.append(f"{key}_max {max(values):.6f}")
            lines.append(f"{key}_avg {avg:.6f}")
    
    return HttpResponse('\n'.join(lines), content_type='text/plain')


@require_GET
def metrics_json_view(request):
    """
    Metrics endpoint in JSON format
    GET /metrics/json/
    """
    data = {
        'counters': dict(_get_counters()),
        'gauges': _get_gauges(),
        'histograms': {}
    }
    
    # Process histograms
    histograms = _get_histograms()
    for key, values in histograms.items():
        if values:
            count = len(values)
            total = sum(values)
            data['histograms'][key] = {
                'count': count,
                'sum': total,
                'min': min(values),
                'max': max(values),
                'avg': total / count
            }
    
    return HttpResponse(json.dumps(data, indent=2), content_type='application/json')
