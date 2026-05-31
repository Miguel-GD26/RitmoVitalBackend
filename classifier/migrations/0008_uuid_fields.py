"""
Migration manual: agrega campo uuid único a Paciente, AnalisisECG y UserProfile.

Se realiza en 3 pasos para compatibilidad con datos existentes:
1. Agregar como nullable
2. Poblar con valores únicos
3. Hacer non-null y unique
"""

import uuid

from django.db import migrations, models


def _populate(apps, schema_editor):
    for Model in ('AnalisisECG', 'Paciente'):
        Mdl = apps.get_model('classifier', Model)
        for obj in Mdl.objects.filter(uuid__isnull=True):
            obj.uuid = uuid.uuid4()
            obj.save(update_fields=['uuid'])

    UserProfile = apps.get_model('classifier', 'UserProfile')
    for obj in UserProfile.objects.filter(uuid__isnull=True):
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('classifier', '0007_user_profile_avatar'),
    ]

    operations = [
        # --- Step 1: add nullable ---
        migrations.AddField(
            model_name='analisisecg',
            name='uuid',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.AddField(
            model_name='paciente',
            name='uuid',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='uuid',
            field=models.UUIDField(null=True, editable=False),
        ),
        # --- Step 2: populate ---
        migrations.RunPython(_populate, migrations.RunPython.noop),
        # --- Step 3: non-null + unique ---
        migrations.AlterField(
            model_name='analisisecg',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name='paciente',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
