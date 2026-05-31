from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classifier', '0002_paciente'),
    ]

    operations = [
        migrations.AddField(
            model_name='analisisecg',
            name='ecg_plot_png',
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='analisisecg',
            name='distribucion_json',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
