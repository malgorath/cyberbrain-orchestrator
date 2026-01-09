"""
Orchestrator service for executing tasks using Docker containers.
This service provides the core functionality for running orchestrator tasks.
"""
import docker
import logging
import hashlib
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
    
    def perform_rag_retrieval(self, job, query_text, top_k=5):
        """
        Phase 3: Perform RAG retrieval for a job.
        
        SECURITY GUARDRAIL: Only stores query hash and result counts.
        Returns top-k relevant chunks.
        """
        from core.models import Embedding, RetrievalEvent
        from core.management.commands.run_ingester import EmbeddingService
        from orchestrator.rag_views import cosine_similarity
        
        logger.info(f"Performing RAG retrieval for job {job.id}")
        
        try:
            # Generate query hash for logging (no plaintext storage)
            query_hash = hashlib.sha256(query_text.encode('utf-8')).hexdigest()
            
            # Generate query embedding
            embedding_service = EmbeddingService()
            query_embedding = embedding_service.embed([query_text])[0]
            
            # Find similar chunks (cosine similarity)
            embeddings = Embedding.objects.select_related('chunk__document').all()
            
            scored_chunks = []
            for emb in embeddings:
                score = cosine_similarity(query_embedding, emb.vector)
                scored_chunks.append({
                    'chunk': emb.chunk,
                    'document': emb.chunk.document,
                    'score': score
                })
            
            # Sort by score and take top-k
            scored_chunks.sort(key=lambda x: x['score'], reverse=True)
            results = scored_chunks[:top_k]
            
            # Log retrieval event (hash only, no query text)
            RetrievalEvent.objects.create(
                run=job.run,
                query_hash=query_hash,
                top_k=top_k,
                results_count=len(results)
            )
            
            logger.info(f"RAG retrieval found {len(results)} results for job {job.id}")
            return results
            
        except Exception as e:
            logger.error(f"RAG retrieval failed for job {job.id}: {e}")
            return []
    
    def execute_log_triage(self, job):
        """
        Execute log triage task.
        Analyzes logs from CYBER_BRAIN_LOGS directory.
        
        Phase 3: If run.use_rag=True, performs retrieval before LLM call.
        """
        logger.info(f"Executing log triage for job {job.id}")
        
        try:
            # Phase 3: RAG retrieval if enabled
            rag_context = ""
            if job.run.use_rag:
                query = "log errors warnings exceptions failures"
                results = self.perform_rag_retrieval(job, query, top_k=3)
                if results:
                    rag_context = "\n\n".join([
                        f"[Doc: {r['document'].title}]\n{r['chunk'].text}"
                        for r in results
                    ])
                    logger.info(f"RAG context added to job {job.id} ({len(results)} chunks)")
            
            # Placeholder implementation
            # In production, this would:
            # 1. Read logs from CYBER_BRAIN_LOGS
            # 2. Optionally use RAG context for analysis
            # 3. Process/analyze logs (potentially using LLM)
            # 4. Store results in job.result
            
            job.result = {
                'task': 'log_triage',
                'status': 'completed',
                'logs_analyzed': 0,
                'issues_found': [],
                'rag_used': job.run.use_rag,
                'rag_chunks_retrieved': len(results) if job.run.use_rag else 0,
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


class RepoCopilotService:
    """
    Phase 6: Repo Co-Pilot service for generating PR plans.
    
    SECURITY GUARDRAIL: No LLM prompts/responses stored. Token counts only.
    DIRECTIVE GATING:
    - D1/D2: Plan only (read-only analysis)
    - D3: Plan + optional branch creation
    - D4: Plan + branch + optional push/PR (with explicit flags)
    
    CONSTRAINTS:
    - Default: read-only clone, plan generation only
    - Branch creation requires D3+ and create_branch_flag=True
    - Push/PR requires D4 + explicit flag
    - All secrets (GitHub tokens) server-side only, never in artifacts
    """
    
    def __init__(self):
        """Initialize Repo Co-Pilot service"""
        self.docker_client = None
        try:
            import docker
            self.docker_client = docker.from_env()
            logger.info("Docker client initialized for RepoCopilotService")
        except Exception as e:
            logger.debug(f"Docker client not available for RepoCopilotService: {e}")
    
    def validate_directive_gating(self, directive, flags):
        """
        Validate that directive allows the requested operations.
        
        Args:
            directive: Directive model instance
            flags: Dict with 'create_branch_flag' and 'push_flag' booleans
        
        Returns:
            Dict with validation result and allowed operations
        
        Raises:
            ValueError: If directive does not allow requested operations
        """
        from core.models import Directive as CoreDirective
        
        if not directive:
            raise ValueError("Directive is required")
        
        # Get directive level from name heuristics
        # D1/D2: plan only, D3: plan + branch, D4: push allowed
        directive_level = self._infer_directive_level(directive)
        
        allowed = {
            'plan': True,  # All levels allow plan
            'create_branch': directive_level >= 3,
            'push': directive_level >= 4,
        }
        
        # Check if requested operations exceed directive level
        if flags.get('create_branch_flag', False) and not allowed['create_branch']:
            raise ValueError(
                f"Directive '{directive.name}' does not allow branch creation. "
                f"Requires D3 or higher."
            )
        
        if flags.get('push_flag', False) and not allowed['push']:
            raise ValueError(
                f"Directive '{directive.name}' does not allow push. "
                f"Requires D4."
            )
        
        return {
            'valid': True,
            'allowed_operations': allowed,
            'directive_level': directive_level,
        }
    
    def _infer_directive_level(self, directive):
        """
        Infer directive level from name.
        
        D1/D2 (level 2): plan only
        D3 (level 3): plan + branch
        D4 (level 4): plan + branch + push + PR
        """
        name_lower = directive.name.lower()
        
        if 'd4' in name_lower or 'level-4' in name_lower:
            return 4
        elif 'd3' in name_lower or 'level-3' in name_lower:
            return 3
        elif 'd1' in name_lower or 'd2' in name_lower or 'level-1' in name_lower or 'level-2' in name_lower:
            return 2
        else:
            # Default to most restrictive (plan only)
            return 2
    
    def generate_plan(self, repo_url, base_branch, goal, directive):
        """
        Generate a repo PR plan without executing changes.
        
        Args:
            repo_url: GitHub repository URL
            base_branch: Base branch for plan (e.g., 'main', 'develop')
            goal: User goal/request for the plan
            directive: Directive model instance for gating
        
        Returns:
            Dict with plan structure:
            {
                'files': [{'path': str, 'action': 'create|modify|delete'}],
                'edits': [{'file': str, 'description': str, 'changes': int}],
                'commands': [{'cmd': str, 'description': str}],
                'checks': [{'type': str, 'description': str}],
                'risk_notes': [str],
                'markdown': str,
            }
        """
        logger.info(f"Generating plan for {repo_url}@{base_branch}: {goal}")
        
        # For MVP: Generate basic plan structure
        # In production, this would use analysis or LLM-based planning
        plan = {
            'files': self._analyze_files(goal),
            'edits': self._analyze_edits(goal),
            'commands': self._analyze_commands(goal),
            'checks': self._analyze_checks(goal),
            'risk_notes': self._assess_risk(goal, directive),
            'markdown': '',
        }
        
        # Generate markdown representation
        plan['markdown'] = self._generate_markdown(plan, repo_url, base_branch, goal)
        
        logger.info(f"Plan generated with {len(plan['files'])} files, {len(plan['edits'])} edits")
        
        return plan
    
    def _analyze_files(self, goal):
        """Analyze goal and return potential files to modify"""
        # MVP: Simple heuristics based on goal keywords
        files = []
        
        goal_lower = goal.lower()
        
        if any(kw in goal_lower for kw in ['config', 'settings', 'environment']):
            files.append({
                'path': 'config/settings.py',
                'action': 'modify',
            })
        
        if any(kw in goal_lower for kw in ['test', 'spec', 'unit test']):
            files.append({
                'path': 'tests/',
                'action': 'create',
            })
        
        if any(kw in goal_lower for kw in ['doc', 'readme', 'documentation']):
            files.append({
                'path': 'README.md',
                'action': 'modify',
            })
        
        if not files:
            files.append({
                'path': 'src/main.py',
                'action': 'modify',
            })
        
        return files
    
    def _analyze_edits(self, goal):
        """Analyze goal and return potential edits"""
        edits = []
        
        goal_lower = goal.lower()
        
        if any(kw in goal_lower for kw in ['add', 'new', 'feature', 'implement']):
            edits.append({
                'file': 'src/main.py',
                'description': 'Add new feature implementation',
                'changes': 10,
            })
        
        if any(kw in goal_lower for kw in ['fix', 'bug', 'issue', 'patch']):
            edits.append({
                'file': 'src/main.py',
                'description': 'Fix identified issue',
                'changes': 5,
            })
        
        if any(kw in goal_lower for kw in ['refactor', 'clean', 'improve', 'optimize']):
            edits.append({
                'file': 'src/main.py',
                'description': 'Refactor for clarity and performance',
                'changes': 15,
            })
        
        if not edits:
            edits.append({
                'file': 'src/main.py',
                'description': 'Implement requested changes',
                'changes': 8,
            })
        
        return edits
    
    def _analyze_commands(self, goal):
        """Analyze goal and return potential commands to run"""
        commands = []
        
        goal_lower = goal.lower()
        
        if any(kw in goal_lower for kw in ['test', 'spec', 'unit test']):
            commands.append({
                'cmd': 'python -m pytest tests/',
                'description': 'Run test suite',
            })
        
        if any(kw in goal_lower for kw in ['lint', 'format', 'style']):
            commands.append({
                'cmd': 'ruff check . && ruff format .',
                'description': 'Lint and format code',
            })
        
        if any(kw in goal_lower for kw in ['build', 'compile', 'package']):
            commands.append({
                'cmd': 'python setup.py build',
                'description': 'Build package',
            })
        
        commands.append({
            'cmd': 'git log --oneline -5',
            'description': 'Show recent commits',
        })
        
        return commands
    
    def _analyze_checks(self, goal):
        """Analyze goal and return validation checks"""
        checks = [
            {
                'type': 'syntax',
                'description': 'Python syntax validation',
            },
            {
                'type': 'imports',
                'description': 'Import correctness check',
            },
            {
                'type': 'tests',
                'description': 'Unit test execution',
            },
        ]
        
        goal_lower = goal.lower()
        
        if any(kw in goal_lower for kw in ['security', 'auth', 'permission']):
            checks.append({
                'type': 'security',
                'description': 'Security review (requires manual approval)',
            })
        
        return checks
    
    def _assess_risk(self, goal, directive):
        """Assess risk level and return risk notes"""
        risk_notes = []
        
        goal_lower = goal.lower()
        
        if any(kw in goal_lower for kw in ['delete', 'remove', 'drop']):
            risk_notes.append(
                'WARNING: Plan includes file/data deletion. '
                'Review carefully before merging.'
            )
        
        if any(kw in goal_lower for kw in ['database', 'schema', 'migration']):
            risk_notes.append(
                'INFO: Database changes detected. '
                'Ensure backward compatibility and test migrations.'
            )
        
        if any(kw in goal_lower for kw in ['security', 'permission', 'auth', 'token']):
            risk_notes.append(
                'SECURITY: Plan affects authentication/authorization. '
                'Requires security review before merge.'
            )
        
        if not risk_notes:
            risk_notes.append('No significant risks identified in this plan.')
        
        return risk_notes
    
    def _generate_markdown(self, plan, repo_url, base_branch, goal):
        """Generate markdown representation of the plan"""
        lines = [
            f'# PR Plan for {repo_url}',
            '',
            f'**Base Branch:** `{base_branch}`',
            '',
            f'**Goal:** {goal}',
            '',
            '## Files to Modify',
            '',
        ]
        
        for f in plan['files']:
            lines.append(f"- `{f['path']}` ({f['action']})")
        
        lines.extend([
            '',
            '## Proposed Edits',
            '',
        ])
        
        for e in plan['edits']:
            lines.append(f"### {e['file']}")
            lines.append(f"{e['description']} (~{e['changes']} line changes)")
            lines.append('')
        
        lines.extend([
            '## Validation Commands',
            '',
        ])
        
        for cmd in plan['commands']:
            lines.append(f"```bash")
            lines.append(f"{cmd['cmd']}")
            lines.append(f"```")
            lines.append(f"_{cmd['description']}_")
            lines.append('')
        
        lines.extend([
            '## Pre-Merge Checks',
            '',
        ])
        
        for check in plan['checks']:
            lines.append(f"- **{check['type'].title()}**: {check['description']}")
        
        lines.extend([
            '',
            '## Risk Assessment',
            '',
        ])
        
        for note in plan['risk_notes']:
            lines.append(f"- {note}")
        
        return '\n'.join(lines)
