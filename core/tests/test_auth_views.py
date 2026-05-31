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
