from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_workerhost_containerinventory_worker_host'),
        ('orchestrator', '0004_run_worker_host_alter_job_task_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='task_key',
            field=models.CharField(max_length=50, unique=True),
        ),
        migrations.CreateModel(
            name='JobQueueItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('claimed', 'Claimed'), ('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('claimed_until', models.DateTimeField(blank=True, null=True)),
                ('claimed_by', models.CharField(blank=True, max_length=255)),
                ('attempts', models.IntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('job', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='queue_item', to='orchestrator.job')),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='job_queue_items', to='orchestrator.run')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='jobqueueitem',
            index=models.Index(fields=['status', 'claimed_until'], name='core_jobque_status_fa1a1e_idx'),
        ),
        migrations.AddIndex(
            model_name='jobqueueitem',
            index=models.Index(fields=['run'], name='core_jobque_run_2e7bd8_idx'),
        ),
    ]
