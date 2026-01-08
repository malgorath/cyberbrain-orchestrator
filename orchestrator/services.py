"""
Orchestrator service for executing tasks using Docker containers.
This service provides the core functionality for running orchestrator tasks.
"""
import docker
import logging
from django.conf import settings
from .models import Run, Job, LLMCall, ContainerAllowlist

logger = logging.getLogger(__name__)


class OrchestratorService:
    """Service for orchestrating Docker container tasks"""
    
    def __init__(self):
        """Initialize Docker client with access to host socket"""
        try:
            self.docker_client = docker.from_env()
            logger.info("Docker client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.docker_client = None
    
    def is_container_allowed(self, container_id):
        """Check if a container is in the allowlist"""
        return ContainerAllowlist.objects.filter(
            container_id=container_id,
            is_active=True
        ).exists()
    
    def get_allowed_containers(self):
        """Get list of allowed containers from allowlist"""
        return ContainerAllowlist.objects.filter(is_active=True)
    
    def execute_log_triage(self, job):
        """
        Execute log triage task.
        Analyzes logs from CYBER_BRAIN_LOGS directory.
        """
        logger.info(f"Executing log triage for job {job.id}")
        
        try:
            # Placeholder implementation
            # In production, this would:
            # 1. Read logs from CYBER_BRAIN_LOGS
            # 2. Process/analyze logs (potentially using LLM)
            # 3. Store results in job.result
            
            job.result = {
                'task': 'log_triage',
                'status': 'completed',
                'logs_analyzed': 0,
                'issues_found': [],
                'summary': 'Log triage task executed (placeholder)'
            }
            
            # Example LLM call tracking (if LLM was used)
            # LLMCall.objects.create(
            #     job=job,
            #     model_name='gpt-4',
            #     prompt_tokens=150,
            #     completion_tokens=300,
            #     total_tokens=450
            # )
            
            return True
        except Exception as e:
            logger.error(f"Error in log triage: {e}")
            job.error_message = str(e)
            return False
    
    def execute_gpu_report(self, job):
        """
        Execute GPU report task.
        Queries Docker containers for GPU information.
        """
        logger.info(f"Executing GPU report for job {job.id}")
        
        try:
            if not self.docker_client:
                raise Exception("Docker client not initialized")
            
            # Placeholder implementation
            # In production, this would:
            # 1. Query containers with GPU access
            # 2. Collect GPU metrics
            # 3. Generate report
            
            gpu_info = []
            allowed_containers = self.get_allowed_containers()
            
            for container_entry in allowed_containers:
                try:
                    container = self.docker_client.containers.get(container_entry.container_id)
                    gpu_info.append({
                        'container_id': container.id[:12],
                        'name': container.name,
                        'status': container.status,
                    })
                except docker.errors.NotFound:
                    logger.warning(f"Container {container_entry.container_id} not found")
            
            job.result = {
                'task': 'gpu_report',
                'status': 'completed',
                'containers_checked': len(allowed_containers),
                'gpu_containers': gpu_info,
                'summary': 'GPU report generated'
            }
            
            return True
        except Exception as e:
            logger.error(f"Error in GPU report: {e}")
            job.error_message = str(e)
            return False
    
    def execute_service_map(self, job):
        """
        Execute service map task.
        Maps running services and their relationships.
        """
        logger.info(f"Executing service map for job {job.id}")
        
        try:
            if not self.docker_client:
                raise Exception("Docker client not initialized")
            
            # Placeholder implementation
            # In production, this would:
            # 1. Query all allowed containers
            # 2. Analyze network connections
            # 3. Build service dependency map
            
            services = []
            allowed_containers = self.get_allowed_containers()
            
            for container_entry in allowed_containers:
                try:
                    container = self.docker_client.containers.get(container_entry.container_id)
                    services.append({
                        'container_id': container.id[:12],
                        'name': container.name,
                        'image': container.image.tags[0] if container.image.tags else 'unknown',
                        'status': container.status,
                        'ports': container.ports if hasattr(container, 'ports') else {},
                    })
                except docker.errors.NotFound:
                    logger.warning(f"Container {container_entry.container_id} not found")
            
            job.result = {
                'task': 'service_map',
                'status': 'completed',
                'services': services,
                'total_services': len(services),
                'summary': 'Service map generated'
            }
            
            return True
        except Exception as e:
            logger.error(f"Error in service map: {e}")
            job.error_message = str(e)
            return False
    
    def execute_job(self, job):
        """Execute a job based on its task type"""
        from django.utils import timezone
        
        logger.info(f"Starting job {job.id} - {job.task_type}")
        job.status = 'running'
        job.started_at = timezone.now()
        job.save()
        
        task_handlers = {
            'log_triage': self.execute_log_triage,
            'gpu_report': self.execute_gpu_report,
            'service_map': self.execute_service_map,
        }
        
        handler = task_handlers.get(job.task_type)
        if not handler:
            logger.error(f"Unknown task type: {job.task_type}")
            job.status = 'failed'
            job.error_message = f"Unknown task type: {job.task_type}"
            job.completed_at = timezone.now()
            job.save()
            return False
        
        success = handler(job)
        
        job.status = 'completed' if success else 'failed'
        job.completed_at = timezone.now()
        job.save()
        
        logger.info(f"Job {job.id} finished with status: {job.status}")
        return success
    
    def execute_run(self, run):
        """Execute all jobs in a run"""
        from django.utils import timezone
        
        logger.info(f"Starting run {run.id}")
        run.status = 'running'
        run.save()
        
        jobs = run.jobs.all().order_by('id')
        results = []
        
        for job in jobs:
            success = self.execute_job(job)
            results.append({
                'job_id': job.id,
                'task_type': job.task_type,
                'success': success,
                'result': job.result
            })
        
        # Generate run report
        all_success = all(r['success'] for r in results)
        
        # Markdown report
        markdown_lines = [
            f"# Orchestrator Run #{run.id}",
            f"",
            f"**Status:** {'Completed' if all_success else 'Failed'}",
            f"**Started:** {run.started_at}",
            f"",
            f"## Jobs",
            f""
        ]
        
        for result in results:
            status_emoji = "✅" if result['success'] else "❌"
            markdown_lines.append(f"### {status_emoji} {result['task_type']}")
            markdown_lines.append(f"- Job ID: {result['job_id']}")
            markdown_lines.append(f"- Status: {'Success' if result['success'] else 'Failed'}")
            if result.get('result', {}).get('summary'):
                markdown_lines.append(f"- Summary: {result['result']['summary']}")
            markdown_lines.append("")
        
        run.report_markdown = "\n".join(markdown_lines)
        
        # JSON report
        run.report_json = {
            'run_id': run.id,
            'status': 'completed' if all_success else 'failed',
            'started_at': run.started_at.isoformat(),
            'jobs': results
        }
        
        run.status = 'completed' if all_success else 'failed'
        run.completed_at = timezone.now()
        run.save()
        
        logger.info(f"Run {run.id} finished with status: {run.status}")
        return all_success
