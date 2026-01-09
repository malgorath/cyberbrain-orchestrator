"""
Security Guardrails Module

CRITICAL GUARDRAILS:
1. NEVER store LLM prompts or responses in the database
2. ONLY store token counts (prompt_tokens, completion_tokens, total_tokens)
3. When DEBUG_REDACTED_MODE is enabled, redact sensitive content from logs
4. All LLM interactions must go through token counting only

This module provides utilities to enforce and verify security guardrails.
"""

import logging
from django.conf import settings
from django.db.models.signals import pre_save
from django.dispatch import receiver


class SecurityGuardrailerViolation(Exception):
    """Raised when a security guardrail would be violated"""
    pass


def redact_sensitive_content(text: str) -> str:
    """
    Redact sensitive content from a string when DEBUG_REDACTED_MODE is enabled.
    
    SECURITY GUARDRAIL: Prevents accidental logging of LLM content
    """
    if not settings.DEBUG_REDACTED_MODE:
        return text
    
    if not text:
        return text
    
    # Redact API keys, tokens, passwords (email-like patterns)
    import re
    
    # Redact patterns that look like secrets
    patterns = [
        (r'api[_-]?key["\']?\s*[=:]\s*[^\s"\',]+', '[REDACTED_API_KEY]'),
        (r'token["\']?\s*[=:]\s*[^\s"\',]+', '[REDACTED_TOKEN]'),
        (r'password["\']?\s*[=:]\s*[^\s"\',]+', '[REDACTED_PASSWORD]'),
        (r'authorization["\']?\s*[=:]\s*bearer\s+[^\s"\',]+', '[REDACTED_AUTH]'),
        # IP addresses
        (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[REDACTED_IP]'),
    ]
    
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result


@receiver(pre_save)
def enforce_no_llm_content_storage(sender, instance, **kwargs):
    """
    SECURITY GUARDRAIL: Prevent LLM prompts/responses from being stored.
    
    This signal handler checks all models before saving to ensure no prompt
    or response content fields are being created.
    """
    from orchestrator.models import LLMCall as OrchestratorLLMCall
    from core.models import LLMCall as CoreLLMCall
    
    # Only apply to LLMCall models
    if not isinstance(instance, (OrchestratorLLMCall, CoreLLMCall)):
        return
    
    # Check for any fields that might contain prompt/response content
    forbidden_fields = ['prompt', 'response', 'prompt_content', 'response_content', 'llm_prompt', 'llm_response']
    
    for field_name in forbidden_fields:
        if hasattr(instance, field_name):
            value = getattr(instance, field_name)
            if value is not None and value != '':
                raise SecurityGuardrailerViolation(
                    f"SECURITY GUARDRAIL VIOLATION: LLMCall.{field_name} cannot store content. "
                    f"Only token counts are allowed. "
                    f"Use prompt_tokens, completion_tokens, total_tokens instead."
                )


class RedactingLogger(logging.Logger):
    """
    Custom logger that redacts sensitive content when DEBUG_REDACTED_MODE is enabled.
    
    SECURITY GUARDRAIL: Prevents LLM content from leaking into logs
    """
    
    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=None):
        if settings.DEBUG_REDACTED_MODE:
            # Redact the message
            if isinstance(msg, str):
                msg = redact_sensitive_content(msg)
            
            # Redact args if they're strings
            if args and isinstance(args, tuple):
                args = tuple(
                    redact_sensitive_content(str(arg)) if isinstance(arg, str) else arg
                    for arg in args
                )
        
        return super()._log(level, msg, args, exc_info=exc_info, extra=extra, stack_info=stack_info)


def get_redacting_logger(name: str) -> RedactingLogger:
    """Get a logger that redacts sensitive content when DEBUG_REDACTED_MODE is enabled"""
    logging.setLoggerClass(RedactingLogger)
    logger = logging.getLogger(name)
    logging.setLoggerClass(logging.Logger)  # Reset to default
    return logger


# Export utilities
__all__ = [
    'SecurityGuardrailerViolation',
    'redact_sensitive_content',
    'enforce_no_llm_content_storage',
    'RedactingLogger',
    'get_redacting_logger',
]
