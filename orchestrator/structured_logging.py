"""
Observability: Structured Logging

Provides JSON-formatted logging for better log aggregation and analysis.
Compatible with ELK stack, Splunk, CloudWatch, etc.
"""

import logging
import json
import datetime
import traceback


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for structured logging"""
    
    def format(self, record):
        """Format a log record as JSON"""
        log_data = {
            'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': ''.join(traceback.format_exception(*record.exc_info))
            }
        
        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_data['extra'] = record.extra_fields
        
        # Add common extra attributes
        extra_attrs = ['run_id', 'job_id', 'task_key', 'directive_id', 'status']
        for attr in extra_attrs:
            if hasattr(record, attr):
                log_data[attr] = getattr(record, attr)
        
        return json.dumps(log_data)


def get_structured_logger(name):
    """
    Get a structured logger instance.
    
    Usage:
        logger = get_structured_logger(__name__)
        logger.info("Run created", extra={'run_id': 123, 'status': 'pending'})
    """
    logger = logging.getLogger(name)
    
    # Don't add handlers if DEBUG mode (use default Django logging)
    # In production, this would be configured via settings.py
    
    return logger


def log_run_event(logger, event_type, run_id, status=None, **kwargs):
    """
    Log a run-related event with structured fields.
    
    Args:
        logger: Logger instance
        event_type: Type of event (e.g., 'created', 'started', 'completed')
        run_id: Run ID
        status: Run status
        **kwargs: Additional fields to log
    """
    extra = {
        'event_type': event_type,
        'run_id': run_id,
    }
    if status:
        extra['status'] = status
    extra.update(kwargs)
    
    logger.info(f"Run {event_type}: {run_id}", extra=extra)


def log_job_event(logger, event_type, job_id, task_key=None, status=None, **kwargs):
    """
    Log a job-related event with structured fields.
    
    Args:
        logger: Logger instance
        event_type: Type of event (e.g., 'created', 'started', 'completed')
        job_id: Job ID
        task_key: Task key (e.g., 'log_triage')
        status: Job status
        **kwargs: Additional fields to log
    """
    extra = {
        'event_type': event_type,
        'job_id': job_id,
    }
    if task_key:
        extra['task_key'] = task_key
    if status:
        extra['status'] = status
    extra.update(kwargs)
    
    logger.info(f"Job {event_type}: {job_id}", extra=extra)


def log_llm_call(logger, model_id, endpoint, tokens, **kwargs):
    """
    Log an LLM API call with structured fields.
    
    Args:
        logger: Logger instance
        model_id: Model identifier
        endpoint: LLM endpoint
        tokens: Token counts dict with 'prompt', 'completion', 'total'
        **kwargs: Additional fields to log
    """
    extra = {
        'event_type': 'llm_call',
        'model_id': model_id,
        'endpoint': endpoint,
        'tokens': tokens,
    }
    extra.update(kwargs)
    
    logger.info(f"LLM call to {model_id}", extra=extra)


def log_error(logger, error_type, message, **kwargs):
    """
    Log an error with structured fields.
    
    Args:
        logger: Logger instance
        error_type: Type of error (e.g., 'validation_error', 'api_error')
        message: Error message
        **kwargs: Additional fields to log
    """
    extra = {
        'event_type': 'error',
        'error_type': error_type,
    }
    extra.update(kwargs)
    
    logger.error(f"{error_type}: {message}", extra=extra)


# Example settings.py configuration:
"""
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'orchestrator.structured_logging.JSONFormatter',
        },
    },
    'handlers': {
        'json_console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'json_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/logs/cyberbrain.json',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 10,
            'formatter': 'json',
        },
    },
    'loggers': {
        'orchestrator': {
            'handlers': ['json_console', 'json_file'],
            'level': 'INFO',
        },
        'core': {
            'handlers': ['json_console', 'json_file'],
            'level': 'INFO',
        },
    },
}
"""
