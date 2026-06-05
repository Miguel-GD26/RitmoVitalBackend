"""
core.email_service — Envío de emails transaccionales (verificación, bienvenida).
"""
import logging

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

_VERIFY_TOKEN_MAX_AGE = 86400  # 24 horas


def generate_verification_token(user) -> str:
    return signing.dumps({'uid': user.pk}, salt='email-verify', compress=True)


def validate_verification_token(token: str) -> int | None:
    """Retorna user.pk si el token es válido y no expiró. None en caso contrario."""
    try:
        data = signing.loads(token, salt='email-verify', max_age=_VERIFY_TOKEN_MAX_AGE)
        return data['uid']
    except (signing.BadSignature, signing.SignatureExpired, KeyError):
        return None


def send_verification_email(user) -> None:
    """Envía el correo de verificación al usuario. Loguea el error si el envío falla."""
    token = generate_verification_token(user)
    verify_url = f"{settings.FRONTEND_URL}/auth/verify-email?token={token}"
    nombre = user.first_name or user.username

    html_message = f"""
    <!DOCTYPE html>
    <html lang="es">
    <body style="font-family: sans-serif; color: #1e293b; max-width: 560px; margin: 0 auto; padding: 24px;">
      <h2 style="color: #174a7a;">Verifica tu correo electrónico — RitmoVital</h2>
      <p>Hola <strong>{nombre}</strong>,</p>
      <p>Tu cuenta en <strong>RitmoVital</strong> ha sido creada por un administrador.</p>
      <p>Por seguridad, debes verificar tu correo antes de usar el sistema.</p>
      <p style="margin: 24px 0;">
        <a href="{verify_url}"
           style="background:#174a7a; color:#fff; padding:12px 24px;
                  border-radius:6px; text-decoration:none; font-weight:600;">
          Verificar correo electrónico
        </a>
      </p>
      <p style="font-size:0.85rem; color:#64748b;">
        Este enlace expira en <strong>24 horas</strong>.<br>
        Si no esperabas esta cuenta, puedes ignorar este mensaje.
      </p>
      <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
      <p style="font-size:0.8rem; color:#94a3b8;">
        Equipo RitmoVital · Sistema de Análisis ECG
      </p>
    </body>
    </html>
    """

    try:
        send_mail(
            subject='Verifica tu correo electrónico — RitmoVital',
            message=f'Verifica tu correo ingresando a: {verify_url}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info("Email de verificación enviado a %s", user.email)
    except Exception:
        logger.exception("Error enviando email de verificación a %s", user.email)
        raise
