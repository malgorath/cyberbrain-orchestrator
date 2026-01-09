"""
E4 Acceptance Tests: Worker Orchestration

ATDD for worker lifecycle management via Docker socket:
- Spawn workers from allowlisted images
- Track worker spawns/stops in WorkerAudit
- Allocate GPU resources when available
- Enforce WorkerImageAllowlist

Contract expectations:
- Only allowlisted images can spawn workers
- GPU allocation is tracked (only one worker per GPU)
- Worker audit records capture all spawns/stops
- Container cleanup happens on Run completion
"""
from django.test import TestCase
from core.models import (
    Job, Run, Directive, WorkerAudit, WorkerImageAllowlist,
    GPUState, ContainerAllowlist
)
from orchestration.worker_service import WorkerOrchestrator
from unittest.mock import MagicMock
import json


class WorkerOrchestrationTests(TestCase):
    """Test worker lifecycle via WorkerOrchestrator"""

    def setUp(self):
        """Create test directive and job"""
        self.directive = Directive.objects.create(
            directive_type="D1",
            name="test-directive",
            directive_text="Test directive",
            version=1,
            is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage",
            name="Test Job",
            default_directive=self.directive,
            is_active=True
        )
        # Allowlist worker image
        WorkerImageAllowlist.objects.create(
            image_name="cyberbrain/worker:latest",
            is_active=True
        )
        # Use mock Docker client for testing (no actual socket needed)
        mock_client = MagicMock()
        self.orchestrator = WorkerOrchestrator(docker_client=mock_client)

    def test_spawn_worker_creates_audit_record(self):
        """Spawning a worker must create WorkerAudit record"""
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="pending"
        )
        
        # Spawn worker (should be mocked in actual implementation)
        worker_id = self.orchestrator.spawn_worker(
            run=run,
            image_name="cyberbrain/worker:latest"
        )
        
        # Verify WorkerAudit created
        audit = WorkerAudit.objects.filter(container_id=worker_id, operation="spawn").first()
        self.assertIsNotNone(audit, "WorkerAudit record not created for spawn")
        self.assertEqual(audit.container_id, worker_id)
        self.assertEqual(audit.image_name, "cyberbrain/worker:latest")
        self.assertTrue(audit.success)

    def test_stop_worker_creates_audit_record(self):
        """Stopping a worker must create WorkerAudit record"""
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="running"
        )
        
        worker_id = self.orchestrator.spawn_worker(
            run=run,
            image_name="cyberbrain/worker:latest"
        )
        
        # Stop worker
        self.orchestrator.stop_worker(run=run, worker_id=worker_id)
        
        # Verify stop audit created
        stop_audit = WorkerAudit.objects.filter(
            container_id=worker_id, 
            operation="stop"
        ).first()
        self.assertIsNotNone(stop_audit, "WorkerAudit record not created for stop")
        self.assertTrue(stop_audit.success)

    def test_spawn_worker_rejects_non_allowlisted_image(self):
        """Attempting to spawn non-allowlisted image must fail"""
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="pending"
        )
        
        # Try to spawn non-allowlisted image
        with self.assertRaises(ValueError) as ctx:
            self.orchestrator.spawn_worker(
                run=run,
                image_name="malicious/image:latest"
            )
        
        self.assertIn("not allowlisted", str(ctx.exception).lower())
        
        # Verify failed audit created
        audit = WorkerAudit.objects.filter(operation="spawn", success=False).first()
        self.assertIsNotNone(audit, "WorkerAudit should record failed spawn attempt")
        self.assertFalse(audit.success)
        self.assertIn("allowlist", audit.error_message.lower())

    def test_spawn_worker_with_gpu_allocation(self):
        """Spawning worker with GPU must allocate GPU and track in GPUState"""
        # Create available GPU
        gpu = GPUState.objects.create(
            gpu_id="0",
            gpu_name="NVIDIA Test GPU",
            total_vram_mb=8192,
            used_vram_mb=0,
            free_vram_mb=8192,
            utilization_percent=0.0,
            is_available=True,
            active_workers=0
        )
        
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="pending"
        )
        
        # Spawn worker requesting GPU
        worker_id = self.orchestrator.spawn_worker(
            run=run,
            image_name="cyberbrain/worker:latest",
            require_gpu=True
        )
        
        # Verify GPU allocated (active_workers incremented)
        gpu.refresh_from_db()
        self.assertEqual(gpu.active_workers, 1)
        
        # Verify audit has GPU info
        audit = WorkerAudit.objects.filter(container_id=worker_id).first()
        self.assertIsNotNone(audit.gpu_assigned)
        self.assertEqual(audit.gpu_assigned, "0")

    def test_spawn_worker_fails_when_no_gpu_available(self):
        """Spawning worker requiring GPU must fail if no GPU available"""
        # Create GPU that's unavailable
        GPUState.objects.create(
            gpu_id="0",
            gpu_name="NVIDIA Test GPU",
            total_vram_mb=8192,
            used_vram_mb=4096,
            free_vram_mb=4096,
            utilization_percent=50.0,
            is_available=False,  # Not available
            active_workers=1
        )
        
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="pending"
        )
        
        # Try to spawn worker requiring GPU
        with self.assertRaises(RuntimeError) as ctx:
            self.orchestrator.spawn_worker(
                run=run,
                image_name="cyberbrain/worker:latest",
                require_gpu=True
            )
        
        self.assertIn("no gpu available", str(ctx.exception).lower())
        
        # Verify failed audit created
        audit = WorkerAudit.objects.filter(operation="spawn", success=False).first()
        self.assertIsNotNone(audit)
        self.assertFalse(audit.success)
        self.assertIn("gpu", audit.error_message.lower())

    def test_stop_worker_releases_gpu(self):
        """Stopping worker must release allocated GPU"""
        # Create GPU
        gpu = GPUState.objects.create(
            gpu_id="0",
            gpu_name="NVIDIA Test GPU",
            total_vram_mb=8192,
            used_vram_mb=0,
            free_vram_mb=8192,
            utilization_percent=0.0,
            is_available=True,
            active_workers=0
        )
        
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="running"
        )
        
        # Spawn worker with GPU
        worker_id = self.orchestrator.spawn_worker(
            run=run,
            image_name="cyberbrain/worker:latest",
            require_gpu=True
        )
        
        # Verify GPU allocated (active_workers incremented)
        gpu.refresh_from_db()
        self.assertEqual(gpu.active_workers, 1)
        
        # Stop worker
        self.orchestrator.stop_worker(run=run, worker_id=worker_id)
        
        # Verify GPU released (active_workers decremented)
        gpu.refresh_from_db()
        self.assertEqual(gpu.active_workers, 0, "GPU active_workers should be decremented after worker stops")

    def test_worker_audit_contains_run_context(self):
        """WorkerAudit must capture run context for debugging"""
        run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=self.directive.name,
            directive_snapshot_text=self.directive.directive_text,
            status="pending"
        )
        
        worker_id = self.orchestrator.spawn_worker(
            run=run,
            image_name="cyberbrain/worker:latest"
        )
        
        audit = WorkerAudit.objects.filter(container_id=worker_id).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.container_id, worker_id)
        self.assertEqual(audit.operation, "spawn")
        self.assertIsNotNone(audit.created_at)
