from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classifier', '0003_analisisecg_pdf_fields'),
    ]

    operations = [
        # 1. Agregar nuevo campo URL (nullable para compatibilidad con registros existentes)
        migrations.AddField(
            model_name='analisisecg',
            name='ecg_plot_url',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
        # 2. Eliminar el campo BinaryField que almacenaba el PNG en la DB
        migrations.RemoveField(
            model_name='analisisecg',
            name='ecg_plot_png',
        ),
        # 3. Agregar índices compuestos para queries frecuentes
        migrations.AddIndex(
            model_name='analisisecg',
            index=models.Index(fields=['usuario', '-fecha'], name='analisis_usuario_fecha_idx'),
        ),
        migrations.AddIndex(
            model_name='analisisecg',
            index=models.Index(fields=['paciente', '-fecha'], name='analisis_paciente_fecha_idx'),
        ),
        migrations.AddIndex(
            model_name='analisisecg',
            index=models.Index(fields=['modo', 'usuario'], name='analisis_modo_usuario_idx'),
        ),
    ]
