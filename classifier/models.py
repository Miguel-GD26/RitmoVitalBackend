"""
classifier.models — Persistencia de análisis ECG y trazabilidad médica.
"""

import uuid as _uuid

from django.contrib.auth.models import User
from django.db import models


class Paciente(models.Model):
    """Datos demográficos del paciente al que pertenece el registro ECG."""

    SEXO_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Femenino'),
        ('O', 'Otro'),
    ]

    TIPO_DOC_CHOICES = [
        ('DNI', 'DNI'),
        ('CE',  'Carné de Extranjería'),
        ('PAS', 'Pasaporte'),
        ('RUC', 'RUC'),
        ('OTR', 'Otro'),
    ]

    uuid             = models.UUIDField(default=_uuid.uuid4, unique=True, editable=False)
    nombre           = models.CharField(max_length=100, blank=True, default='')
    apellido         = models.CharField(max_length=100, blank=True, default='')
    fecha_nacimiento = models.DateField(null=True, blank=True)
    sexo             = models.CharField(max_length=1, choices=SEXO_CHOICES, blank=True)
    tipo_documento   = models.CharField(max_length=10, choices=TIPO_DOC_CHOICES, blank=True, default='DNI')
    numero_documento = models.CharField(max_length=20, blank=True, default='')
    historia_clinica = models.CharField(max_length=50, unique=True, blank=True)
    notas            = models.TextField(blank=True)
    creado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pacientes_creados',
    )
    usuario_cuenta = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='paciente_perfil',
        help_text='Cuenta de usuario del paciente en el sistema (opcional)',
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['apellido', 'nombre']
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'

    def __str__(self):
        return f"{self.apellido}, {self.nombre}"


class AnalisisECG(models.Model):
    """Registro de cada sesión de análisis ECG procesada por el sistema."""

    MODO_CHOICES = [
        ('demo', 'Demo'),
        ('anotado', 'Con Anotaciones'),
        ('produccion', 'Producción'),
    ]

    uuid    = models.UUIDField(default=_uuid.uuid4, unique=True, editable=False)
    usuario = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='analisis_ecg',
    )
    paciente = models.ForeignKey(
        Paciente, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='analisis',
    )
    record_name      = models.CharField(max_length=100, blank=True)
    modo             = models.CharField(max_length=15, choices=MODO_CHOICES, default='demo')
    fecha            = models.DateTimeField(auto_now_add=True)
    total_latidos    = models.IntegerField(default=0)
    latidos_procesados = models.IntegerField(default=0)
    accuracy         = models.FloatField(null=True, blank=True)
    modelo_version   = models.CharField(max_length=100, default='ultra_best.keras')
    ecg_plot_url     = models.URLField(max_length=500, blank=True, null=True)
    distribucion_json = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Análisis ECG'
        verbose_name_plural = 'Análisis ECG'
        indexes = [
            models.Index(fields=['usuario', '-fecha']),
            models.Index(fields=['paciente', '-fecha']),
            models.Index(fields=['modo', 'usuario']),
        ]

    def __str__(self):
        return f"{self.record_name or 'demo'} — {self.usuario} — {self.fecha:%Y-%m-%d %H:%M}"


from core.models import AuditLog  # noqa: F401  # movido a core/models.py
