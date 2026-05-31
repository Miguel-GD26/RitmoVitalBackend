"""
core.models — Modelos de infraestructura transversal.

Usa app_label = 'classifier' para mantener la tabla DB existente sin migraciones.
"""

import uuid as _uuid

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """Perfil extendido del usuario — avatar y datos adicionales."""

    TIPO_DOC_CHOICES = [
        ('DNI', 'DNI'),
        ('CE',  'Carné de Extranjería'),
        ('PAS', 'Pasaporte'),
        ('RUC', 'RUC'),
        ('OTR', 'Otro'),
    ]

    SEXO_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Femenino'),
        ('O', 'Otro'),
    ]

    user             = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    uuid             = models.UUIDField(default=_uuid.uuid4, unique=True, editable=False)
    avatar_url       = models.URLField(max_length=500, null=True, blank=True)
    tipo_documento   = models.CharField(max_length=10, choices=TIPO_DOC_CHOICES, blank=True, default='DNI')
    numero_documento = models.CharField(max_length=20, blank=True, default='')
    fecha_nacimiento = models.DateField(null=True, blank=True)
    sexo             = models.CharField(max_length=1, choices=SEXO_CHOICES, blank=True, default='')
    # Médico
    numero_colegiatura = models.CharField(max_length=30, blank=True, default='')
    # Investigador
    orcid       = models.CharField(max_length=50, blank=True, default='')
    institucion = models.CharField(max_length=150, blank=True, default='')
    # 2FA — TOTP (Google Authenticator / Authy)
    totp_secret  = models.CharField(max_length=64, blank=True, default='')
    totp_enabled = models.BooleanField(default=False)

    class Meta:
        app_label = 'classifier'
        verbose_name = 'Perfil de usuario'

    def __str__(self):
        return f"Perfil de {self.user.username}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


class AuditLog(models.Model):
    """Registro de accesos a endpoints con datos médicos (trazabilidad HIPAA/LOPD)."""

    usuario    = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs',
    )
    accion     = models.CharField(max_length=10)
    endpoint   = models.CharField(max_length=200)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'classifier'  # mantiene la tabla classifier_auditlog sin migración
        ordering = ['-timestamp']
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        indexes = [
            models.Index(fields=['-timestamp'], name='auditlog_timestamp_idx'),
            models.Index(fields=['usuario', '-timestamp'], name='auditlog_usuario_ts_idx'),
        ]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} — {self.usuario} — {self.endpoint}"
