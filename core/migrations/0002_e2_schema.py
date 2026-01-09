# Generated manually for E2 schema alignment
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='default_directive',
            field=models.ForeignKey(
                blank=True,
                help_text='Default directive applied to this task (D1/D2/D3)',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='default_for_jobs',
                to='core.directive',
            ),
        ),
        migrations.RemoveField(
            model_name='run',
            name='directive_snapshot',
        ),
        migrations.RemoveField(
            model_name='run',
            name='total_completion_tokens',
        ),
        migrations.RemoveField(
            model_name='run',
            name='total_prompt_tokens',
        ),
        migrations.RemoveField(
            model_name='run',
            name='total_tokens',
        ),
        migrations.AddField(
            model_name='run',
            name='directive_snapshot_name',
            field=models.CharField(blank=True, default='', help_text='Directive name captured at run time (no content stored)', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='run',
            name='directive_snapshot_text',
            field=models.TextField(blank=True, help_text='Directive text captured at run time (no prompts/responses)'),
        ),
        migrations.AddField(
            model_name='run',
            name='token_completion',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='run',
            name='token_prompt',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='run',
            name='token_total',
            field=models.IntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name='run',
            index=models.Index(fields=['job', 'status', 'ended_at'], name='idx_run_job_status_ended'),
        ),
        migrations.AddIndex(
            model_name='llmcall',
            index=models.Index(fields=['run', 'endpoint', 'model_id', 'created_at'], name='idx_llmcall_tokens'),
        ),
    ]
