"""
Tests de integración para endpoints de autenticación JWT (auth_views.py).

Cubre:
  - Login: cookies HttpOnly, credenciales inválidas, usuario inactivo
  - Refresh: sin cookie → 401, con cookie válida → 200
  - Logout: borra cookies
  - Me: requiere autenticación, retorna datos de usuario
  - ALLOW_BEARER_FALLBACK=False: el header Authorization se ignora en producción
  - LoginRateThrottle: 5 intentos/min, 6° request → 429
  - RBAC: endpoint de admin requiere is_staff, usuario regular → 403
"""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

# Sin throttling global, pero la tasa de 'login' debe existir porque
# CookieLoginView.throttle_classes = [LoginRateThrottle] es un atributo de clase
# que no puede eliminarse vía override_settings.  Usamos DummyCache para que el
# LoginRateThrottle no acumule estado entre tests.
TEST_REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
    'DEFAULT_AUTHENTICATION_CLASSES': ['core.authentication.CookieJWTAuthentication'],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
    ],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {'login': '1000/minute'},
}

# DummyCache garantiza que cada request al login endpoint empieza con contador 0.
DUMMY_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE)
class LoginViewTests(TestCase):
    """POST /api/auth/login/ — flujo de autenticación con cookies HttpOnly."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='medico_test',
            email='medico@test.com',
            password='TestPass123!',
        )

    def test_valid_credentials_return_200(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['success'])

    def test_login_sets_access_token_cookie(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertIn('access_token', response.cookies)

    def test_login_sets_refresh_token_cookie(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertIn('refresh_token', response.cookies)

    def test_access_cookie_is_httponly(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertTrue(response.cookies['access_token']['httponly'])

    def test_refresh_cookie_is_httponly(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertTrue(response.cookies['refresh_token']['httponly'])

    def test_response_body_does_not_contain_token_values(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        body = response.json()
        # Los tokens no deben estar en el body (protección XSS)
        self.assertNotIn('access', body.get('data', {}))
        self.assertNotIn('refresh', body.get('data', {}))

    def test_wrong_password_returns_400(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com', 'password': 'WrongPassword!'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.json()['success'])

    def test_nonexistent_email_returns_400(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'noexiste@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.json()['success'])

    def test_inactive_user_returns_400(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.json()['success'])

    def test_missing_email_returns_400(self):
        response = self.client.post(
            '/api/auth/login/',
            {'password': 'TestPass123!'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_password_returns_400(self):
        response = self.client.post(
            '/api/auth/login/',
            {'email': 'medico@test.com'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE)
class LogoutViewTests(TestCase):
    """POST /api/auth/logout/ — eliminación de cookies."""

    def setUp(self):
        self.client = APIClient()

    def test_logout_returns_200(self):
        response = self.client.post('/api/auth/logout/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['success'])

    def test_logout_deletes_access_cookie(self):
        response = self.client.post('/api/auth/logout/')
        # Django marca las cookies eliminadas con max_age=0
        if 'access_token' in response.cookies:
            self.assertEqual(response.cookies['access_token']['max-age'], 0)

    def test_logout_does_not_require_auth(self):
        # Permite logout incluso sin sesión activa (token expirado)
        response = self.client.post('/api/auth/logout/')
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE)
class RefreshViewTests(TestCase):
    """POST /api/auth/refresh/ — renovación de access token."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='refresh_user',
            email='refresh@test.com',
            password='TestPass123!',
        )
        self.client = APIClient()

    def test_refresh_without_cookie_returns_401(self):
        response = self.client.post('/api/auth/refresh/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(response.json()['success'])

    def test_refresh_with_valid_cookie_returns_200(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.cookies['refresh_token'] = str(refresh)
        response = self.client.post('/api/auth/refresh/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['success'])

    def test_refresh_emits_new_access_cookie(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.cookies['refresh_token'] = str(refresh)
        response = self.client.post('/api/auth/refresh/')
        self.assertIn('access_token', response.cookies)

    def test_refresh_with_invalid_token_returns_error(self):
        self.client.cookies['refresh_token'] = 'invalid.token.here'
        response = self.client.post('/api/auth/refresh/')
        self.assertIn(response.status_code, [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
        ])


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE)
class CurrentUserViewTests(TestCase):
    """GET /api/auth/me/ — verificación de sesión activa."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='me_user',
            email='me@test.com',
            password='TestPass123!',
        )
        self.client = APIClient()

    def test_me_requires_authentication(self):
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_user_data_when_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()['data']
        self.assertEqual(data['username'], 'me_user')
        self.assertEqual(data['email'], 'me@test.com')
        self.assertIn('groups', data)
        self.assertIn('is_superuser', data)

    def test_me_response_includes_id(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/auth/me/')
        self.assertIn('id', response.json()['data'])


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE, ALLOW_BEARER_FALLBACK=False)
class BearerFallbackDisabledTests(TestCase):
    """
    En producción ALLOW_BEARER_FALLBACK=False — el header Authorization
    no puede sustituir a la cookie HttpOnly.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='bearer_user',
            email='bearer@test.com',
            password='TestPass123!',
        )
        self.client = APIClient()

    def test_bearer_token_in_header_is_ignored(self):
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        # Sin cookie — solo header Authorization
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cookie_token_still_works(self):
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        # Con cookie — debe funcionar normalmente
        self.client.cookies['access_token'] = access_token
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE)
class RbacTests(TestCase):
    """RBAC — admin endpoints requieren is_staff=True."""

    def setUp(self):
        self.client = APIClient()

    def test_admin_users_endpoint_blocks_regular_user(self):
        regular = User.objects.create_user(
            username='regular_user', email='regular@test.com', password='pass'
        )
        self.client.force_authenticate(user=regular)
        response = self.client.get('/api/v1/admin/users/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_users_endpoint_allows_staff(self):
        staff = User.objects.create_user(
            username='staff_user', email='staff@test.com', password='pass',
            is_staff=True,
        )
        self.client.force_authenticate(user=staff)
        response = self.client.get('/api/v1/admin/users/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_users_endpoint_requires_auth(self):
        response = self.client.get('/api/v1/admin/users/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(
    REST_FRAMEWORK={
        **TEST_REST_FRAMEWORK,
        'DEFAULT_THROTTLE_RATES': {'login': '3/minute'},
    },
)
class LoginThrottleTests(TestCase):
    """LoginRateThrottle — bloquea tras superar 3 intentos/min en este test."""

    def setUp(self):
        # LocMemCache del entorno de desarrollo — limpiar estado previo
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user(
            username='throttle_victim',
            email='throttle@test.com',
            password='TestPass123!',
        )

    @patch('rest_framework.throttling.SimpleRateThrottle.THROTTLE_RATES', {'login': '3/minute'})
    def test_login_throttle_returns_429_after_limit(self):
        # SimpleRateThrottle.THROTTLE_RATES se fija en import-time, por eso
        # override_settings solo no alcanza — hacemos patch directo aquí.
        client = APIClient()
        last_response = None
        for _ in range(4):  # 1 más que el límite de 3/minute
            last_response = client.post(
                '/api/auth/login/',
                {'email': 'throttle@test.com', 'password': 'WrongPass!'},
                format='json',
                REMOTE_ADDR='10.9.9.9',
            )
        self.assertEqual(last_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE)
class ProfileViewTests(TestCase):
    """
    GET/PATCH /api/v1/auth/profile/ — perfil editable del usuario autenticado.

    Cubre el bug: PATCH con fecha_nacimiento='' producía 500 porque DateField
    no acepta cadena vacía. Corregido en ProfileView.patch con conversión a None.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='profile_user',
            email='profile@test.com',
            password='TestPass123!',
            first_name='Juan',
            last_name='Pérez',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # ── GET ──────────────────────────────────────────────────────────────────

    def test_get_profile_returns_200(self):
        response = self.client.get('/api/v1/auth/profile/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['success'])

    def test_get_profile_returns_correct_fields(self):
        response = self.client.get('/api/v1/auth/profile/')
        data = response.json()['data']
        self.assertEqual(data['email'], 'profile@test.com')
        self.assertEqual(data['username'], 'profile_user')
        self.assertIn('first_name', data)
        self.assertIn('last_name', data)
        self.assertIn('email_verified', data)
        self.assertIn('must_change_password', data)

    def test_get_profile_requires_auth(self):
        client = APIClient()  # sin autenticar
        response = client.get('/api/v1/auth/profile/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── PATCH — casos normales ────────────────────────────────────────────────

    def test_patch_name_returns_200(self):
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {'first_name': 'Carlos', 'last_name': 'López'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['success'])

    def test_patch_name_persists(self):
        self.client.patch(
            '/api/v1/auth/profile/',
            {'first_name': 'Nuevo', 'last_name': 'Apellido'},
            format='json',
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Nuevo')
        self.assertEqual(self.user.last_name, 'Apellido')

    def test_patch_sexo_returns_200(self):
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {'sexo': 'M'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ── PATCH — regresión: fecha_nacimiento vacía no debe producir 500 ────────

    def test_patch_empty_fecha_nacimiento_returns_200_not_500(self):
        """
        Regresión: PATCH con fecha_nacimiento='' producía 500 (DataError en DB).
        DateField no acepta cadena vacía — debe convertirse a None.
        """
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {
                'first_name': 'Juan',
                'last_name': 'Pérez',
                'fecha_nacimiento': '',
                'sexo': '',
                'numero_colegiatura': '',
                'orcid': '',
                'institucion': '',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['success'])

    def test_patch_valid_fecha_nacimiento_persists(self):
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {'fecha_nacimiento': '1990-05-15'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        from core.models import UserProfile
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(str(profile.fecha_nacimiento), '1990-05-15')

    def test_patch_null_fecha_nacimiento_persists(self):
        """Enviar null explícito también debe funcionar."""
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {'fecha_nacimiento': None},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_patch_does_not_allow_changing_email(self):
        """El email es de solo lectura — enviar email en PATCH no debe modificarlo."""
        self.client.patch(
            '/api/v1/auth/profile/',
            {'email': 'hacker@evil.com'},
            format='json',
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'profile@test.com')

    def test_patch_does_not_allow_changing_numero_documento(self):
        """El número de documento es de solo lectura."""
        from core.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.numero_documento = '12345678'
        profile.save()

        self.client.patch(
            '/api/v1/auth/profile/',
            {'numero_documento': '99999999'},
            format='json',
        )
        profile.refresh_from_db()
        self.assertEqual(profile.numero_documento, '12345678')


LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE)
class VerifyEmailViewTests(TestCase):
    """POST /api/v1/auth/verify-email/ — validación del token de verificación."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='unverified', email='unverified@test.com', password='Pass123!'
        )
        from core.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.email_verified = False
        profile.save()

    def _valid_token(self):
        from core.email_service import generate_verification_token
        return generate_verification_token(self.user)

    def test_valid_token_returns_200(self):
        resp = self.client.post(
            '/api/v1/auth/verify-email/', {'token': self._valid_token()}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()['success'])

    def test_valid_token_marks_email_as_verified(self):
        self.client.post(
            '/api/v1/auth/verify-email/', {'token': self._valid_token()}, format='json'
        )
        from core.models import UserProfile
        profile = UserProfile.objects.get(user=self.user)
        self.assertTrue(profile.email_verified)

    def test_invalid_token_returns_400(self):
        resp = self.client.post(
            '/api/v1/auth/verify-email/', {'token': 'garbage-token-xyz'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.json()['success'])

    def test_expired_token_returns_400(self):
        with patch('core.email_service.validate_verification_token', return_value=None):
            resp = self.client.post(
                '/api/v1/auth/verify-email/', {'token': self._valid_token()}, format='json'
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_token_returns_error(self):
        resp = self.client.post('/api/v1/auth/verify-email/', {}, format='json')
        self.assertIn(resp.status_code, [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ])

    def test_already_verified_is_idempotent(self):
        from core.models import UserProfile
        profile = UserProfile.objects.get(user=self.user)
        profile.email_verified = True
        profile.save()
        resp = self.client.post(
            '/api/v1/auth/verify-email/', {'token': self._valid_token()}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=LOCMEM_CACHE)
class SendVerificationEmailViewTests(TestCase):
    """POST /api/v1/auth/send-verification-email/ — reenvío de email de verificación."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='vsender', email='vsender@test.com', password='Pass123!'
        )
        # Usar el objeto cacheado por el signal post_save para que la vista
        # acceda al mismo objeto y vea los valores actualizados.
        self.user.profile.email_verified = False
        self.user.profile.save(update_fields=['email_verified'])
        self.client.force_authenticate(user=self.user)

    @patch('core.email_service.send_mail')
    def test_envia_email_y_retorna_200(self, mock_mail):
        resp = self.client.post('/api/v1/auth/send-verification-email/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()['success'])
        mock_mail.assert_called_once()

    @patch('core.email_service.send_mail')
    def test_correo_ya_verificado_retorna_400(self, _):
        self.user.profile.email_verified = True
        self.user.profile.save(update_fields=['email_verified'])
        resp = self.client.post('/api/v1/auth/send-verification-email/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('core.email_service.send_mail')
    def test_segundo_envio_en_cooldown_retorna_429(self, _):
        self.client.post('/api/v1/auth/send-verification-email/')
        resp = self.client.post('/api/v1/auth/send-verification-email/')
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_requiere_autenticacion(self):
        resp = APIClient().post('/api/v1/auth/send-verification-email/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Cambio de contraseña
# ---------------------------------------------------------------------------

@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=DUMMY_CACHE)
class ChangePasswordViewTests(TestCase):
    """POST /api/v1/auth/change-password/ — cambio voluntario y forzado de contraseña."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='pass_changer', email='pchanger@test.com', password='OldPass123!'
        )
        self.client.force_authenticate(user=self.user)

    def test_cambio_voluntario_con_password_correcta_retorna_200(self):
        resp = self.client.post('/api/v1/auth/change-password/', {
            'current_password': 'OldPass123!',
            'new_password': 'NewPass456!',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()['success'])

    def test_nueva_password_queda_guardada(self):
        self.client.post('/api/v1/auth/change-password/', {
            'current_password': 'OldPass123!',
            'new_password': 'NewPass456!',
        }, format='json')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass456!'))

    def test_password_actual_incorrecta_retorna_400(self):
        resp = self.client.post('/api/v1/auth/change-password/', {
            'current_password': 'Wronggg!',
            'new_password': 'NewPass456!',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nueva_password_menor_a_8_chars_retorna_400(self):
        resp = self.client.post('/api/v1/auth/change-password/', {
            'current_password': 'OldPass123!',
            'new_password': 'short',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_misma_password_retorna_400(self):
        resp = self.client.post('/api/v1/auth/change-password/', {
            'current_password': 'OldPass123!',
            'new_password': 'OldPass123!',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cambio_forzado_no_requiere_password_actual(self):
        self.user.profile.must_change_password = True
        self.user.profile.save(update_fields=['must_change_password'])
        resp = self.client.post('/api/v1/auth/change-password/', {
            'new_password': 'NewPass456!',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_cambio_forzado_limpia_flag_must_change_password(self):
        self.user.profile.must_change_password = True
        self.user.profile.save(update_fields=['must_change_password'])
        self.client.post('/api/v1/auth/change-password/', {
            'new_password': 'NewPass456!',
        }, format='json')
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.must_change_password)

    def test_requiere_autenticacion(self):
        resp = APIClient().post('/api/v1/auth/change-password/', {
            'current_password': 'OldPass123!',
            'new_password': 'NewPass456!',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
