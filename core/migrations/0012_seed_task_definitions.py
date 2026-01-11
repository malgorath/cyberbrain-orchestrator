from django.db import migrations


def seed_task_definitions(apps, schema_editor):
    Job = apps.get_model('core', 'Job')
    defaults = [
        ('log_triage', 'Log Triage'),
        ('gpu_report', 'GPU Report'),
        ('service_map', 'Service Map'),
    ]
    for key, name in defaults:
        Job.objects.get_or_create(task_key=key, defaults={'name': name, 'is_active': True})


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_jobqueueitem_and_job_task_key_unique'),
    ]

    operations = [
        migrations.RunPython(seed_task_definitions, migrations.RunPython.noop),
    ]
