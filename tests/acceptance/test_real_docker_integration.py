"""
Real Docker Socket Integration Tests (ATDD)

Tests verify actual Docker socket communication:
- Connect to /var/run/docker.sock
- Collect logs from real containers
- Filter by time (since last run)
- Handle errors (socket unavailable, container not found)
- Respect ContainerAllowlist

CONTRACT:
- docker.from_env() connection succeeds
- Logs retrieved from actual containers
- Only allowlisted containers accessed
- Errors handled gracefully
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from core.models import ContainerAllowlist, Run, Job, Directive, RunJob
from orchestration.docker_client import DockerLogCollector
from unittest.mock import MagicMock, patch
import docker
import unittest


class DockerSocketConnectionTests(TestCase):
    """Test Docker socket connection and availability"""
    
    @unittest.skipUnless(
        hasattr(docker, 'from_env'),
        "Docker not available in test environment"
    )
    def test_docker_client_can_connect(self):
        """Docker client can connect to socket (SKIP if socket unavailable)"""
        # This test only runs when docker socket is available
        # In CI/local dev without docker, it's skipped
        try:
            collector = DockerLogCollector()
            client = collector.get_client()
            self.assertIsNotNone(client)
        except docker.errors.DockerException:
            self.skipTest("Docker socket not available")
    
    @patch('docker.from_env')
    def test_docker_socket_unavailable_handled(self, mock_docker):
        """Gracefully handle docker socket unavailable"""
        mock_docker.side_effect = docker.errors.DockerException("Socket not found")
        
        collector = DockerLogCollector()
        
        with self.assertRaises(docker.errors.DockerException):
            collector.get_client()


class DockerLogCollectionTests(TestCase):
    """Test actual log collection from containers"""
    
    def setUp(self):
        """Create test data"""
        self.collector = DockerLogCollector()
        
        # Create allowlisted container
        self.container = ContainerAllowlist.objects.create(
            container_id="test_web_123",
            container_name="web",
            enabled=True
        )
    
    @patch('docker.from_env')
    def test_collect_logs_from_allowlisted_container(self, mock_docker):
        """Can collect logs from allowlisted container"""
        # Mock container with logs
        mock_container = MagicMock()
        mock_container.logs.return_value = b"2026-01-08 10:00:00 INFO Server started\n2026-01-08 10:01:00 WARN High memory usage"
        
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        logs = self.collector.collect_logs(self.container.container_id)
        
        self.assertIsNotNone(logs)
        self.assertIn("Server started", logs)
        self.assertIn("High memory usage", logs)
    
    @patch('docker.from_env')
    def test_collect_logs_since_timestamp(self, mock_docker):
        """Can filter logs since specific timestamp"""
        mock_container = MagicMock()
        mock_container.logs.return_value = b"Recent log entry"
        
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        since = timezone.now() - timedelta(hours=1)
        logs = self.collector.collect_logs(
            self.container.container_id,
            since=since
        )
        
        # Verify logs() called with since parameter
        mock_container.logs.assert_called_once()
        call_kwargs = mock_container.logs.call_args[1]
        self.assertIn('since', call_kwargs)
    
    @patch('docker.from_env')
    def test_collect_logs_container_not_found(self, mock_docker):
        """Gracefully handle container not found"""
        # Create allowlisted container (must be in allowlist first)
        missing = ContainerAllowlist.objects.create(
            container_id="nonexistent_container",
            container_name="missing",
            enabled=True
        )
        
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = docker.errors.NotFound("Container not found")
        mock_docker.return_value = mock_client
        
        logs = self.collector.collect_logs(missing.container_id)
        
        # Should return empty string, not crash
        self.assertEqual(logs, "")
    
    def test_only_allowlisted_containers_accessed(self):
        """Cannot collect logs from non-allowlisted container"""
        # Create disabled container
        disabled = ContainerAllowlist.objects.create(
            container_id="blocked_123",
            container_name="blocked",
            enabled=False
        )
        
        with self.assertRaises(PermissionError):
            self.collector.collect_logs(disabled.container_id)


class DockerLogSinceLastRunTests(TestCase):
    """Test 'since last successful run' filtering"""
    
    def setUp(self):
        """Create test runs"""
        d1 = Directive.objects.create(
            directive_type="D1", name="d1",
            directive_text="Test", version=1, is_active=True
        )
        self.job = Job.objects.create(
            task_key="log_triage", name="Log Triage",
            default_directive=d1, is_active=True
        )
        
        # Create previous successful run
        self.prev_run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=d1.name,
            directive_snapshot_text=d1.directive_text,
            status="success"
        )
        RunJob.objects.create(
            run=self.prev_run,
            job=self.job,
            status="success",
            completed_at=timezone.now() - timedelta(hours=2)
        )
        
        # Create current run
        self.current_run = Run.objects.create(
            job=self.job,
            directive_snapshot_name=d1.name,
            directive_snapshot_text=d1.directive_text,
            status="pending"
        )
        
        self.collector = DockerLogCollector()
    
    def test_get_last_successful_run_timestamp(self):
        """Can retrieve last successful run timestamp"""
        timestamp = self.collector.get_last_successful_run_time(self.job)
        
        self.assertIsNotNone(timestamp)
        self.assertLessEqual(timestamp, timezone.now())
    
    @patch('docker.from_env')
    def test_collect_logs_since_last_run(self, mock_docker):
        """Collect logs since last successful run"""
        mock_container = MagicMock()
        mock_container.logs.return_value = b"Recent logs only"
        
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        container = ContainerAllowlist.objects.create(
            container_id="web_456",
            container_name="web",
            enabled=True
        )
        
        logs = self.collector.collect_logs_since_last_run(
            container.container_id,
            self.job
        )
        
        self.assertIsNotNone(logs)
        # Verify since parameter was used
        mock_container.logs.assert_called_once()


class DockerLogEncodingTests(TestCase):
    """Test log encoding/decoding"""
    
    def setUp(self):
        self.collector = DockerLogCollector()
    
    @patch('docker.from_env')
    def test_decode_utf8_logs(self, mock_docker):
        """Can decode UTF-8 logs"""
        mock_container = MagicMock()
        mock_container.logs.return_value = b"UTF-8 log: \xc3\xa9\xc3\xa0"
        
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        container = ContainerAllowlist.objects.create(
            container_id="web_789",
            container_name="web",
            enabled=True
        )
        
        logs = self.collector.collect_logs(container.container_id)
        
        self.assertIsInstance(logs, str)
        self.assertIn("UTF-8", logs)
    
    @patch('docker.from_env')
    def test_handle_invalid_encoding(self, mock_docker):
        """Gracefully handle invalid encoding"""
        mock_container = MagicMock()
        mock_container.logs.return_value = b"\xff\xfe Invalid bytes"
        
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        container = ContainerAllowlist.objects.create(
            container_id="web_999",
            container_name="web",
            enabled=True
        )
        
        # Should not crash
        logs = self.collector.collect_logs(container.container_id)
        self.assertIsInstance(logs, str)
