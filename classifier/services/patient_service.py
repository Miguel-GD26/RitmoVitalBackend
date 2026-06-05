"""
classifier.services.patient_service — Lógica de dominio para vinculación de pacientes.
"""
import logging

from django.contrib.auth.models import User, Group
from django.db import transaction

from classifier.models import Paciente
from core.models import UserProfile

logger = logging.getLogger(__name__)


class PacienteYaVinculadoError(Exception):
    """El paciente ya tiene una cuenta de usuario vinculada."""


class UsuarioYaVinculadoError(Exception):
    """El usuario ya está vinculado a otro paciente."""


def vincular_cuenta_existente(paciente: Paciente, email: str) -> None:
    """Vincula el paciente a una cuenta de usuario ya existente."""
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise User.DoesNotExist

    if Paciente.objects.filter(usuario_cuenta=user).exists():
        raise UsuarioYaVinculadoError

    paciente.usuario_cuenta = user
    paciente.save(update_fields=['usuario_cuenta'])


def crear_y_vincular_cuenta(paciente: Paciente, email: str, password: str) -> User:
    """
    Crea un usuario con rol paciente, configura su perfil con los datos del paciente
    y lo vincula. Envía el correo de verificación.

    Raises ValueError si la contraseña es inválida.
    """
    if len(password) < 6:
        raise ValueError("Mínimo 6 caracteres.")

    with transaction.atomic():
        username = _unique_username(email.split('@')[0])

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=paciente.nombre,
            last_name=paciente.apellido,
        )
        group, _ = Group.objects.get_or_create(name='paciente')
        user.groups.add(group)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.tipo_documento       = paciente.tipo_documento
        profile.numero_documento     = paciente.numero_documento
        profile.email_verified       = False
        profile.must_change_password = True
        profile.save(update_fields=[
            'tipo_documento', 'numero_documento',
            'email_verified', 'must_change_password',
        ])

        paciente.usuario_cuenta = user
        paciente.save(update_fields=['usuario_cuenta'])

    from core.email_service import send_verification_email
    try:
        send_verification_email(user)
    except Exception:
        logger.warning("No se pudo enviar email de verificación a %s", email)

    logger.info("Cuenta creada y vinculada: paciente=%s user=%s", paciente.pk, email)
    return user


def _unique_username(base: str) -> str:
    username, counter = base, 1
    while User.objects.filter(username=username).exists():
        username = f'{base}{counter}'
        counter += 1
    return username
