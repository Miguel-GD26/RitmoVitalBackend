import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classifier', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Paciente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100)),
                ('apellido', models.CharField(max_length=100)),
                ('fecha_nacimiento', models.DateField(blank=True, null=True)),
                ('sexo', models.CharField(
                    blank=True, max_length=1,
                    choices=[('M', 'Masculino'), ('F', 'Femenino'), ('O', 'Otro')],
                )),
                ('historia_clinica', models.CharField(blank=True, max_length=50, unique=True)),
                ('notas', models.TextField(blank=True)),
                ('fecha_registro', models.DateTimeField(auto_now_add=True)),
                ('creado_por', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pacientes_creados',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Paciente',
                'verbose_name_plural': 'Pacientes',
                'ordering': ['apellido', 'nombre'],
            },
        ),
        migrations.AddField(
            model_name='analisisecg',
            name='paciente',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='analisis',
                to='classifier.paciente',
            ),
        ),
    ]
