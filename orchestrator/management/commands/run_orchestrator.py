"""
Management command to execute orchestrator runs.
Usage: python manage.py run_orchestrator <run_id>
"""
from django.core.management.base import BaseCommand, CommandError
from orchestrator.models import Run
from orchestrator.services import OrchestratorService


class Command(BaseCommand):
    help = 'Execute an orchestrator run'

    def add_arguments(self, parser):
        parser.add_argument('run_id', type=int, help='Run ID to execute')

    def handle(self, *args, **options):
        run_id = options['run_id']
        
        try:
            run = Run.objects.get(id=run_id)
        except Run.DoesNotExist:
            raise CommandError(f'Run "{run_id}" does not exist')
        
        self.stdout.write(self.style.SUCCESS(f'Starting run {run_id}...'))
        
        orchestrator = OrchestratorService()
        success = orchestrator.execute_run(run)
        
        if success:
            self.stdout.write(self.style.SUCCESS(f'Run {run_id} completed successfully!'))
        else:
            self.stdout.write(self.style.ERROR(f'Run {run_id} failed.'))
            raise CommandError('Run execution failed')
