from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orchestrator', '0004_run_worker_host_alter_job_task_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='run',
            name='directive_snapshot',
            field=models.JSONField(blank=True, default=dict, help_text='Snapshot of directive metadata at run creation (no LLM content)'),
        ),
    ]
