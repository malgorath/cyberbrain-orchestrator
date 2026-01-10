from django.core.management import call_command
from django.test import TestCase
from unittest.mock import patch


class RunSchedulerCommandTests(TestCase):
    @patch('core.management.commands.run_scheduler.Command._tick', side_effect=KeyboardInterrupt)
    def test_call_command_accepts_claim_ttl(self, mock_tick):
        """call_command should accept claim_ttl/interval without KeyError."""
        # Should not raise KeyError for 'claim_ttl' option
        call_command('run_scheduler', interval=1, claim_ttl=2)
