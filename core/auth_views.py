"""
core.auth_views — Endpoints de autenticación JWT con cookies HttpOnly.

Flujo de seguridad:
  - Login:   valida credenciales → emite access + refresh en cookies HttpOnly
  - Refresh: lee refresh de cookie → emite nuevo access en cookie (+ rota refresh)
  - Logout:  borra ambas cookies del navegador

Las cookies son HttpOnly (inaccesibles a JavaScript) y Secure en producción,
lo que elimina el vector de robo de token via XSS comparado con localStorage.
"""

import base64
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import serializers
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from core.responses import ApiResponse

# Tiempo de vida del token temporal de 2FA (segundos)
_2FA_TOKEN_MAX_AGE = 300  # 5 minutos

logger = logging.getLogger(__name__)


class LoginRateThrottle(AnonRateThrottle):
    """5 intentos de login por minuto por IP — más restrictivo que el global de 30/min."""
    scope = 'login'


class EmailLoginSerializer(serializers.Serializer):
    """Autentica con email + password. Retorna el objeto User — los tokens se emiten en la vista."""
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email    = data['email'].strip().lower()
        password = data['password']

        try:
            user = User.objects.select_related('profile').get(email__iexact=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {'email': ['No existe una cuenta registrada con este correo.']}
            )

        if not user.check_password(password):
            raise serializers.ValidationError(
                {'password': ['Contraseña incorrecta.']}
            )

        if not user.is_active:
            raise serializers.ValidationError(
                {'email': ['Esta cuenta está desactivada.']}
            )

        # Retornar el user — los JWT se crean en la vista SOLO si no hay 2FA.
        # Así se evita crear tokens que quedan huérfanos cuando 2FA bloquea el login.
        return {'user': user}


def _set_access_cookie(response, access_token: str) -> None:
    response.set_cookie(
        key=settings.JWT_ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path='/',
    )


def _set_refresh_cookie(response, refresh_token: str) -> None:
    response.set_cookie(
        key=settings.JWT_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path='/',
    )


@extend_schema(
    tags=['auth'],
    summary='Login — obtener tokens JWT via cookies HttpOnly',
    request=EmailLoginSerializer,
    responses={
        200: OpenApiResponse(description='Login exitoso — tokens emitidos en cookies HttpOnly'),
        401: OpenApiResponse(description='Credenciales inválidas'),
    },
)
class CookieLoginView(APIView):
    """
    POST /api/auth/login/

    Body: { "email": "...", "password": "..." }

    Respuesta exitosa: HTTP 200 + cookies HttpOnly (access_token, refresh_token).
    El cuerpo de la respuesta NO contiene los tokens (seguridad XSS).
    """
    permission_classes = [AllowAny]
    throttle_classes   = [LoginRateThrottle]  # 5 intentos/min por IP

    def post(self, request):
        serializer = EmailLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # El serializer ya cargó el usuario con select_related('profile') — sin segunda query.
        user    = serializer.validated_data['user']
        profile = getattr(user, 'profile', None)

        if profile and profile.totp_enabled and profile.totp_secret:
            temp_token = signing.dumps({'uid': user.pk}, salt='2fa-login', compress=True)
            return ApiResponse.success(
                data={'requires_2fa': True, 'temp_token': temp_token},
                message="Código 2FA requerido",
                status_code=202,
            )

        # Solo creamos tokens cuando 2FA no está activo — evita tokens huérfanos.
        refresh = RefreshToken.for_user(user)
        response = ApiResponse.success(data={}, message="Login exitoso")
        _set_access_cookie(response, str(refresh.access_token))
        _set_refresh_cookie(response, str(refresh))
        return response


@extend_schema(
    tags=['auth'],
    summary='Refresh — renovar access token usando cookie refresh',
    request=None,
    responses={
        200: OpenApiResponse(description='Nuevo access token emitido en cookie'),
        401: OpenApiResponse(description='No hay refresh token o está expirado'),
    },
)
class CookieRefreshView(APIView):
    """
    POST /api/auth/refresh/

    No necesita body. Lee el refresh token desde la cookie HttpOnly.
    Emite un nuevo access token (y rota el refresh si ROTATE_REFRESH_TOKENS=True).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if not refresh_token:
            return ApiResponse.error(
                message="Sesión expirada. Por favor inicia sesión nuevamente.",
                errors={"detail": "refresh_token cookie no presente"},
                error_code="NO_REFRESH_TOKEN",
                status_code=401,
            )

        serializer = TokenRefreshSerializer(data={'refresh': refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        response = ApiResponse.success(
            data={},
            message="Token renovado exitosamente",
        )
        _set_access_cookie(response, serializer.validated_data['access'])

        # Rotar refresh token si SimpleJWT lo emitió uno nuevo
        new_refresh = serializer.validated_data.get('refresh')
        if new_refresh:
            _set_refresh_cookie(response, new_refresh)

        return response


@extend_schema(
    tags=['auth'],
    summary='Logout — eliminar cookies de autenticación',
    request=None,
    responses={200: OpenApiResponse(description='Logout exitoso — cookies eliminadas')},
)
class LogoutView(APIView):
    """
    POST /api/auth/logout/

    Elimina las cookies de autenticación del navegador.
    No requiere autenticación (permite logout incluso con token expirado).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        response = ApiResponse.success(
            data={},
            message="Logout exitoso",
        )
        response.delete_cookie(settings.JWT_ACCESS_COOKIE_NAME, path='/')
        response.delete_cookie(settings.JWT_REFRESH_COOKIE_NAME, path='/')
        return response


@extend_schema(
    tags=['auth'],
    summary='Google OAuth — intercambiar authorization code por JWT cookies',
    request=None,
    responses={
        200: OpenApiResponse(description='Login exitoso — JWT cookies emitidas'),
        400: OpenApiResponse(description='Código inválido o error de Google'),
    },
)
class GoogleAuthView(APIView):
    """
    POST /api/auth/google/

    Body: { "code": "<authorization_code>", "redirect_uri": "<uri>" }

    Intercambia el authorization code de Google por tokens JWT emitidos
    en cookies HttpOnly. Crea el usuario si no existe.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        import requests as http_requests
        from django.contrib.auth.models import Group

        code = request.data.get('code')
        redirect_uri = request.data.get('redirect_uri', settings.GOOGLE_REDIRECT_URI)

        if not code:
            return ApiResponse.validation_error(
                errors={'code': ['Campo requerido']},
                message='Código de autorización requerido',
            )

        try:
            token_resp = http_requests.post(
                'https://oauth2.googleapis.com/token',
                data={
                    'code': code,
                    'client_id': settings.GOOGLE_CLIENT_ID,
                    'client_secret': settings.GOOGLE_CLIENT_SECRET,
                    'redirect_uri': redirect_uri,
                    'grant_type': 'authorization_code',
                },
                timeout=10,
            )
            token_data = token_resp.json()
            access_token = token_data.get('access_token')

            if not access_token:
                logger.warning("Google token exchange failed: %s", token_data.get('error'))
                return ApiResponse.error(
                    message='No se pudo autenticar con Google',
                    errors={'google': [token_data.get('error_description', 'Código inválido o expirado')]},
                    error_code='GOOGLE_AUTH_FAILED',
                    status_code=400,
                )

            userinfo_resp = http_requests.get(
                'https://www.googleapis.com/oauth2/v2/userinfo',
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10,
            )
            userinfo = userinfo_resp.json()
            email = userinfo.get('email')

            if not email:
                return ApiResponse.error(
                    message='No se pudo obtener el email de Google',
                    errors={'google': ['Email no disponible en la cuenta Google']},
                    error_code='GOOGLE_NO_EMAIL',
                    status_code=400,
                )

            user = User.objects.filter(email=email).first()
            if user is None:
                base_username = email.split('@')[0]
                username = base_username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f'{base_username}{counter}'
                    counter += 1
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=None,
                )
                # Asignar rol paciente automáticamente a cuentas Google nuevas
                paciente_group, _ = Group.objects.get_or_create(name='paciente')
                user.groups.add(paciente_group)
                logger.info("Usuario paciente creado via Google OAuth: %s", email)

            refresh = RefreshToken.for_user(user)
            response = ApiResponse.success(
                data={'username': user.username, 'email': user.email},
                message='Login con Google exitoso',
            )
            _set_access_cookie(response, str(refresh.access_token))
            _set_refresh_cookie(response, str(refresh))
            return response

        except Exception:
            logger.exception("Error en Google OAuth")
            return ApiResponse.error(
                message='Error al procesar autenticación con Google',
                errors={'google': ['Error interno del servidor']},
                error_code='GOOGLE_AUTH_ERROR',
                status_code=500,
            )


@extend_schema(
    tags=['auth'],
    summary='2FA Verify — validar código TOTP y emitir JWT cookies',
    request=None,
    responses={
        200: OpenApiResponse(description='Código válido — JWT cookies emitidas'),
        400: OpenApiResponse(description='Código inválido o temp_token expirado'),
    },
)
class Verify2FAView(APIView):
    """
    POST /api/auth/2fa/verify/

    Body: { "temp_token": "<token>", "code": "<6-digit TOTP>" }

    Valida el código TOTP contra el secreto del usuario y emite JWT cookies
    si es correcto. El temp_token expira en 5 minutos.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        import pyotp
        temp_token = request.data.get('temp_token', '')
        code = request.data.get('code', '').strip()

        if not temp_token or not code:
            return ApiResponse.validation_error(
                errors={'detail': ['temp_token y code son requeridos']},
                message='Datos incompletos',
            )

        try:
            data = signing.loads(temp_token, salt='2fa-login', max_age=_2FA_TOKEN_MAX_AGE)
            user = User.objects.get(pk=data['uid'])
        except (signing.BadSignature, signing.SignatureExpired, User.DoesNotExist):
            return ApiResponse.error(
                message='Token temporal inválido o expirado. Inicia sesión de nuevo.',
                error_code='INVALID_2FA_TOKEN',
                status_code=400,
            )

        profile = getattr(user, 'profile', None)
        if not profile or not profile.totp_enabled or not profile.totp_secret:
            return ApiResponse.error(
                message='2FA no está configurado para este usuario.',
                error_code='2FA_NOT_CONFIGURED',
                status_code=400,
            )

        totp = pyotp.TOTP(profile.totp_secret)
        if not totp.verify(code, valid_window=1):
            return ApiResponse.error(
                message='Código incorrecto. Verifica tu aplicación autenticadora.',
                error_code='INVALID_TOTP_CODE',
                status_code=400,
            )

        refresh = RefreshToken.for_user(user)
        response = ApiResponse.success(data={}, message="Login exitoso con 2FA")
        _set_access_cookie(response, str(refresh.access_token))
        _set_refresh_cookie(response, str(refresh))
        return response


@extend_schema(
    tags=['auth'],
    summary='2FA Setup — generar secreto TOTP y QR para el usuario autenticado',
    request=None,
    responses={
        200: OpenApiResponse(description='Secreto y URI para QR generados'),
        400: OpenApiResponse(description='2FA ya habilitado'),
    },
)
class TOTPSetupView(APIView):
    """
    GET  /api/auth/2fa/setup/ → genera secreto + provisioning URI (para QR)
    POST /api/auth/2fa/setup/ { "code": "123456" } → confirma el secreto y habilita 2FA
    DELETE /api/auth/2fa/setup/ { "code": "123456" } → deshabilita 2FA
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import pyotp
        profile = request.user.profile
        if profile.totp_enabled:
            return ApiResponse.error(
                message='2FA ya está habilitado. Deshabilítalo primero para generar un nuevo secreto.',
                error_code='2FA_ALREADY_ENABLED',
                status_code=400,
            )
        secret = pyotp.random_base32()
        # Guardar secreto pendiente de confirmación (aún no habilitado)
        profile.totp_secret = secret
        profile.totp_enabled = False
        profile.save(update_fields=['totp_secret', 'totp_enabled'])

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=request.user.email,
            issuer_name='RitmoVital',
        )
        return ApiResponse.success(
            data={'secret': secret, 'provisioning_uri': provisioning_uri},
            message='Escanea el QR con tu app autenticadora y confirma con un código',
        )

    def post(self, request):
        import pyotp
        code = request.data.get('code', '').strip()
        profile = request.user.profile

        if not profile.totp_secret:
            return ApiResponse.error(
                message='Primero genera el secreto con GET /api/auth/2fa/setup/',
                error_code='2FA_SECRET_MISSING',
                status_code=400,
            )
        if profile.totp_enabled:
            return ApiResponse.error(
                message='2FA ya está habilitado.',
                error_code='2FA_ALREADY_ENABLED',
                status_code=400,
            )

        totp = pyotp.TOTP(profile.totp_secret)
        if not totp.verify(code, valid_window=1):
            return ApiResponse.error(
                message='Código incorrecto. Asegúrate de que la hora del dispositivo esté sincronizada.',
                error_code='INVALID_TOTP_CODE',
                status_code=400,
            )

        profile.totp_enabled = True
        profile.save(update_fields=['totp_enabled'])
        return ApiResponse.success(data={}, message='2FA habilitado correctamente')

    def delete(self, request):
        import pyotp
        code = request.data.get('code', '').strip()
        profile = request.user.profile

        if not profile.totp_enabled:
            return ApiResponse.error(
                message='2FA no está habilitado.',
                error_code='2FA_NOT_ENABLED',
                status_code=400,
            )

        totp = pyotp.TOTP(profile.totp_secret)
        if not totp.verify(code, valid_window=1):
            return ApiResponse.error(
                message='Código incorrecto.',
                error_code='INVALID_TOTP_CODE',
                status_code=400,
            )

        profile.totp_secret = ''
        profile.totp_enabled = False
        profile.save(update_fields=['totp_secret', 'totp_enabled'])
        return ApiResponse.success(data={}, message='2FA deshabilitado correctamente')


# ---------------------------------------------------------------------------
# Verificación de email
# ---------------------------------------------------------------------------

class SendVerificationEmailView(APIView):
    """POST /api/v1/auth/send-verification-email/ — reenvía el email de verificación."""
    permission_classes = [IsAuthenticated]

    _COOLDOWN_KEY = 'verify_email_cooldown:{uid}'
    _COOLDOWN_SECONDS = 120  # 2 minutos entre reenvíos

    def post(self, request):
        from django.core.cache import cache
        from core.email_service import send_verification_email

        profile = getattr(request.user, 'profile', None)
        if profile and profile.email_verified:
            return ApiResponse.error(
                message='El correo ya está verificado.',
                error_code='EMAIL_ALREADY_VERIFIED',
                status_code=400,
            )

        cooldown_key = self._COOLDOWN_KEY.format(uid=request.user.pk)
        if cache.get(cooldown_key):
            return ApiResponse.error(
                message='Espera 2 minutos antes de reenviar el correo.',
                error_code='EMAIL_COOLDOWN',
                status_code=429,
            )

        try:
            send_verification_email(request.user)
        except Exception:
            return ApiResponse.error(
                message='No se pudo enviar el correo. Intenta más tarde.',
                error_code='EMAIL_SEND_ERROR',
                status_code=500,
            )

        cache.set(cooldown_key, True, timeout=self._COOLDOWN_SECONDS)
        return ApiResponse.success(
            data={},
            message=f'Correo de verificación enviado a {request.user.email}.',
        )


class VerifyEmailView(APIView):
    """POST /api/v1/auth/verify-email/ — valida el token y marca el correo como verificado."""
    permission_classes = [AllowAny]

    def post(self, request):
        from core.email_service import validate_verification_token

        token = request.data.get('token', '').strip()
        if not token:
            return ApiResponse.validation_error(
                errors={'token': ['El token es requerido.']},
                message='Token faltante',
            )

        uid = validate_verification_token(token)
        if uid is None:
            return ApiResponse.error(
                message='El enlace de verificación es inválido o ha expirado.',
                error_code='INVALID_VERIFY_TOKEN',
                status_code=400,
            )

        try:
            user = User.objects.get(pk=uid)
        except User.DoesNotExist:
            return ApiResponse.not_found('Usuario no encontrado.')

        profile = getattr(user, 'profile', None)
        if profile and not profile.email_verified:
            profile.email_verified = True
            profile.save(update_fields=['email_verified'])

        return ApiResponse.success(data={}, message='Correo verificado correctamente.')


# ---------------------------------------------------------------------------
# Cambio de contraseña
# ---------------------------------------------------------------------------

class ChangePasswordView(APIView):
    """POST /api/v1/auth/change-password/ — cambia la contraseña del usuario autenticado."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get('current_password', '')
        new_password     = request.data.get('new_password', '')

        if not new_password or len(new_password) < 8:
            return ApiResponse.validation_error(
                errors={'new_password': ['La contraseña debe tener al menos 8 caracteres.']},
                message='Contraseña inválida',
            )

        profile = getattr(request.user, 'profile', None)
        forced  = profile.must_change_password if profile else False

        if not forced:
            if not current_password:
                return ApiResponse.validation_error(
                    errors={'current_password': ['La contraseña actual es requerida.']},
                    message='Contraseña actual faltante',
                )
            if not request.user.check_password(current_password):
                return ApiResponse.validation_error(
                    errors={'current_password': ['La contraseña actual es incorrecta.']},
                    message='Contraseña incorrecta',
                )

        if new_password == current_password and not forced:
            return ApiResponse.validation_error(
                errors={'new_password': ['La nueva contraseña debe ser diferente a la actual.']},
                message='Contraseña sin cambios',
            )

        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])

        if profile and profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=['must_change_password'])

        # Rotar tokens: el cliente debe re-autenticarse con la nueva contraseña
        refresh = RefreshToken.for_user(request.user)
        response = ApiResponse.success(data={}, message='Contraseña actualizada correctamente.')
        _set_access_cookie(response, str(refresh.access_token))
        _set_refresh_cookie(response, str(refresh))
        return response


# ---------------------------------------------------------------------------
# Perfil del usuario autenticado
# ---------------------------------------------------------------------------

class ProfileView(APIView):
    """GET/PATCH /api/v1/auth/profile/ — perfil editable del usuario autenticado."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user    = request.user
        profile = getattr(user, 'profile', None)
        groups  = list(user.groups.values_list('name', flat=True))
        return ApiResponse.success(
            data=self._serialize(user, profile, groups),
            message='Perfil obtenido',
        )

    def patch(self, request):
        user    = request.user
        profile = getattr(user, 'profile', None)

        user_fields    = ('first_name', 'last_name')
        profile_fields = ('fecha_nacimiento', 'sexo', 'numero_colegiatura', 'orcid', 'institucion')

        user_changed    = False
        profile_changed = False

        # Cambio de username con validación de unicidad
        if 'username' in request.data:
            new_username = request.data['username'].strip()
            if new_username and new_username != user.username:
                if User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                    return ApiResponse.validation_error(
                        errors={'username': ['Este nombre de usuario ya está en uso.']},
                        message='Nombre de usuario no disponible',
                    )
                user.username = new_username
                user_changed = True

        for field in user_fields:
            if field in request.data:
                setattr(user, field, request.data[field])
                user_changed = True
        if user_changed:
            save_fields = [f for f in user_fields if f in request.data]
            if 'username' in request.data and request.data['username'].strip():
                save_fields.append('username')
            user.save(update_fields=save_fields)

        if profile:
            # Solo los DateField/nullable aceptan None; CharFields aceptan cadena vacía
            _nullable = frozenset({'fecha_nacimiento'})
            for field in profile_fields:
                if field in request.data:
                    value = request.data[field]
                    if field in _nullable and value == '':
                        value = None
                    setattr(profile, field, value)
                    profile_changed = True
            if profile_changed:
                changed = [f for f in profile_fields if f in request.data]
                profile.save(update_fields=changed)
                # Refrescar para que los campos tengan tipos Python correctos
                # (ej: fecha_nacimiento queda como str en memoria tras setattr)
                profile.refresh_from_db(fields=changed)

        groups = list(user.groups.values_list('name', flat=True))
        return ApiResponse.success(
            data=self._serialize(user, profile, groups),
            message='Perfil actualizado',
        )

    @staticmethod
    def _serialize(user, profile, groups):
        return {
            'id':               user.id,
            'username':         user.username,
            'email':            user.email,
            'first_name':       user.first_name,
            'last_name':        user.last_name,
            'groups':           groups,
            'is_superuser':     user.is_superuser,
            'avatar_url':       profile.avatar_url if profile else None,
            'tipo_documento':   profile.tipo_documento if profile else '',
            'numero_documento': profile.numero_documento if profile else '',
            'fecha_nacimiento': profile.fecha_nacimiento.isoformat() if (profile and profile.fecha_nacimiento) else None,
            'sexo':             profile.sexo if profile else '',
            'numero_colegiatura': profile.numero_colegiatura if profile else '',
            'orcid':            profile.orcid if profile else '',
            'institucion':      profile.institucion if profile else '',
            'email_verified':        profile.email_verified if profile else True,
            'must_change_password':  profile.must_change_password if profile else False,
        }


class ProfileAvatarView(APIView):
    """POST /api/v1/auth/profile/avatar/ — sube o actualiza el avatar del usuario autenticado."""
    from rest_framework.parsers import MultiPartParser
    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        file = request.FILES.get('avatar')
        if not file:
            return ApiResponse.validation_error(
                errors={'avatar': ['Se requiere un archivo de imagen.']},
                message='Archivo faltante',
            )

        allowed = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
        if file.content_type not in allowed:
            return ApiResponse.validation_error(
                errors={'avatar': ['Formato no permitido. Use JPG, PNG, GIF o WebP.']},
                message='Formato inválido',
            )

        if file.size > 2 * 1024 * 1024:
            return ApiResponse.validation_error(
                errors={'avatar': ['El avatar no puede superar 2 MB.']},
                message='Archivo muy grande',
            )

        profile = getattr(request.user, 'profile', None)
        if not profile:
            return ApiResponse.error(message='Perfil no encontrado.', status_code=404)

        try:
            import cloudinary.uploader
            result = cloudinary.uploader.upload(
                file,
                folder='ritmovital/avatars',
                public_id=f'user_{request.user.pk}',
                overwrite=True,
                resource_type='image',
                transformation=[{'width': 256, 'height': 256, 'crop': 'fill', 'gravity': 'face'}],
            )
            profile.avatar_url = result['secure_url']
            profile.save(update_fields=['avatar_url'])
            return ApiResponse.success(
                data={'avatar_url': profile.avatar_url},
                message='Avatar actualizado correctamente.',
            )
        except Exception:
            logger.exception("Error subiendo avatar del usuario %s", request.user.pk)
            return ApiResponse.error(
                message='No se pudo subir el avatar. Intenta más tarde.',
                status_code=500,
            )


@extend_schema(
    tags=['auth'],
    summary='Me — datos del usuario autenticado (verificación de sesión)',
    request=None,
    responses={
        200: OpenApiResponse(description='Usuario autenticado — retorna id, username y grupos'),
        401: OpenApiResponse(description='No autenticado — sesión inválida o expirada'),
    },
)
class CurrentUserView(APIView):
    """
    GET /api/auth/me/

    Usado por el frontend en cada page refresh para verificar si la sesión
    (cookie HttpOnly) sigue vigente. Retorna id, username y grupos Django.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        groups = list(user.groups.values_list('name', flat=True))
        profile = getattr(user, 'profile', None)
        return ApiResponse.success(
            data={
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'groups': groups,
                'is_superuser': user.is_superuser,
                'avatar_url': profile.avatar_url if profile else None,
                'email_verified': profile.email_verified if profile else True,
                'must_change_password': profile.must_change_password if profile else False,
            },
            message="Usuario autenticado",
        )
