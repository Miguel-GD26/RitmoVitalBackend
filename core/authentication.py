"""
core.authentication — Autenticación JWT via cookies HttpOnly.

Lee el access token desde una cookie HttpOnly en lugar del header
Authorization, previniendo exposición del token via JavaScript (XSS).
Hace fallback al header si la cookie no está presente, para compatibilidad
con herramientas como Postman o scripts de testing.
"""

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'core.authentication.CookieJWTAuthentication'
    name = 'cookieJWTAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': settings.JWT_ACCESS_COOKIE_NAME,
            'description': 'JWT access token en cookie HttpOnly. Se envía automáticamente por el navegador.',
        }


class CookieJWTAuthentication(JWTAuthentication):
    """
    JWT authentication que lee el access token desde la cookie HttpOnly.

    Prioridad:
      1. Cookie `access_token` (flujo normal de la app)
      2. Header `Authorization: Bearer <token>` (Postman, tests, scripts)
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE_NAME)
        if raw_token is None:
            if not getattr(settings, 'ALLOW_BEARER_FALLBACK', False):
                return None
            return super().authenticate(request)
        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token

    def get_user(self, validated_token):
        """Single-query fetch with prefetched groups.

        Eliminates the extra DB round-trip that IsMedico/IsInvestigador would
        otherwise trigger on every request via groups.filter(name=...).exists().
        """
        from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
        from rest_framework_simplejwt.settings import api_settings

        try:
            user_id = validated_token[api_settings.USER_ID_CLAIM]
        except KeyError:
            raise InvalidToken("Token contained no recognizable user identification")

        try:
            user = self.user_model.objects.prefetch_related('groups').get(
                **{api_settings.USER_ID_FIELD: user_id}
            )
        except self.user_model.DoesNotExist:
            raise AuthenticationFailed("User not found", code="user_not_found")

        if not user.is_active:
            raise AuthenticationFailed("User is inactive", code="user_inactive")

        return user
