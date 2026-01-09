"""
Phase 4: Notification Service

Sends notifications to configured targets when runs complete.

SECURITY GUARDRAIL: Payloads contain counts only, no LLM content.
"""
import logging
import json
import requests
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from core.models import NotificationTarget, RunNotification

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for sending run status notifications.
    
    Supports:
    - Discord webhooks
    - Email notifications
    
    Payloads are counts-only (no LLM content).
    """
    
    @staticmethod
    def send_run_notification(run):
        """
        Send notifications for a completed run to all enabled targets.
        
        Args:
            run: orchestrator.Run instance
        """
        targets = NotificationTarget.objects.filter(enabled=True)
        
        if not targets.exists():
            logger.debug("No enabled notification targets configured")
            return
        
        for target in targets:
            # Create notification record
            notification = RunNotification.objects.create(
                run=run,
                target=target,
                status='pending'
            )
            
            try:
                if target.type == 'discord':
                    NotificationService._send_discord(run, target, notification)
                elif target.type == 'email':
                    NotificationService._send_email(run, target, notification)
                else:
                    raise ValueError(f"Unsupported notification type: {target.type}")
                
                # Mark as sent
                notification.status = 'sent'
                notification.sent_at = timezone.now()
                notification.save(update_fields=['status', 'sent_at'])
                
                logger.info(f"Notification sent to {target.name} for run {run.id}")
                
            except Exception as e:
                logger.error(f"Failed to send notification to {target.name}: {e}", exc_info=True)
                notification.status = 'failed'
                notification.error_summary = str(e)[:1000]
                notification.save(update_fields=['status', 'error_summary'])
    
    @staticmethod
    def _send_discord(run, target, notification):
        """Send Discord webhook notification."""
        webhook_url = target.config.get('webhook_url')
        if not webhook_url:
            raise ValueError("Discord webhook_url not configured")
        
        # Build counts-only payload (no LLM content)
        from orchestrator.models import LLMCall
        
        llm_calls = LLMCall.objects.filter(job__run=run)
        total_tokens = sum(call.total_tokens for call in llm_calls)
        
        jobs_count = run.jobs.count()
        jobs_completed = run.jobs.filter(status='completed').count()
        jobs_failed = run.jobs.filter(status='failed').count()
        
        # Build embed
        color = 3066993 if run.status == 'completed' else 15158332  # Green or red
        
        embed = {
            "title": f"Run #{run.id} - {run.status.upper()}",
            "description": f"Directive: {run.directive.name}",
            "color": color,
            "fields": [
                {"name": "Status", "value": run.status, "inline": True},
                {"name": "Jobs", "value": f"{jobs_completed}/{jobs_count} completed", "inline": True},
                {"name": "LLM Tokens", "value": str(total_tokens), "inline": True},
            ],
            "timestamp": run.completed_at.isoformat() if run.completed_at else timezone.now().isoformat()
        }
        
        if run.error_message:
            embed["fields"].append({"name": "Error", "value": run.error_message[:1000], "inline": False})
        
        payload = {
            "embeds": [embed]
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
    
    @staticmethod
    def _send_email(run, target, notification):
        """Send email notification."""
        email_address = target.config.get('email')
        if not email_address:
            raise ValueError("Email address not configured")
        
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cyberbrain.local')
        
        # Build counts-only email body
        from orchestrator.models import LLMCall
        
        llm_calls = LLMCall.objects.filter(job__run=run)
        total_tokens = sum(call.total_tokens for call in llm_calls)
        
        jobs_count = run.jobs.count()
        jobs_completed = run.jobs.filter(status='completed').count()
        
        subject = f"Run #{run.id} - {run.status.upper()} - {run.directive.name}"
        
        body = f"""
Run #{run.id} has completed with status: {run.status}

Directive: {run.directive.name}
Status: {run.status}
Jobs: {jobs_completed}/{jobs_count} completed
LLM Tokens: {total_tokens}

Started: {run.started_at.isoformat()}
Completed: {run.completed_at.isoformat() if run.completed_at else 'N/A'}

---
Cyberbrain Orchestrator
"""
        
        if run.error_message:
            body += f"\nError: {run.error_message[:500]}"
        
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[email_address],
            fail_silently=False
        )
    
    @staticmethod
    def test_notification(target):
        """
        Send a test notification to verify configuration.
        
        Args:
            target: NotificationTarget instance
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            if target.type == 'discord':
                webhook_url = target.config.get('webhook_url')
                if not webhook_url:
                    return False, "Discord webhook_url not configured"
                
                payload = {
                    "embeds": [{
                        "title": "Test Notification",
                        "description": f"Test from {target.name}",
                        "color": 3447003,  # Blue
                        "timestamp": timezone.now().isoformat()
                    }]
                }
                
                response = requests.post(webhook_url, json=payload, timeout=10)
                response.raise_for_status()
                return True, "Test notification sent successfully"
                
            elif target.type == 'email':
                email_address = target.config.get('email')
                if not email_address:
                    return False, "Email address not configured"
                
                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cyberbrain.local')
                
                send_mail(
                    subject="Cyberbrain Test Notification",
                    message="This is a test notification from Cyberbrain Orchestrator.",
                    from_email=from_email,
                    recipient_list=[email_address],
                    fail_silently=False
                )
                return True, "Test email sent successfully"
            
            else:
                return False, f"Unsupported notification type: {target.type}"
                
        except Exception as e:
            logger.error(f"Test notification failed for {target.name}: {e}", exc_info=True)
            return False, str(e)
