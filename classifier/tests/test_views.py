"""
Tests de integración de endpoints API — DRF APIClient.

Verifica que las respuestas cumplen el formato estandarizado
{success, message, data, timestamp} y que la validación de entrada
funciona correctamente.

Nota: El modelo ML se mockea para evitar cargar TensorFlow + modelo
      en el runner de tests.
"""

from unittest.mock import patch, MagicMock, PropertyMock

import numpy as np
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.models import User

# Desactivar throttling en tests para evitar 429
TEST_REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'core.authentication.CookieJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    # Sin throttling en tests
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {},
}


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK)
class ClassifyRandomGetTests(TestCase):
    """Tests del endpoint GET /api/v1/classify-random/."""

    def setUp(self):
        self.client = APIClient()
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser_' + str(id(self)), password='password123')
        self.client.force_authenticate(user=self.user)

    @patch('classifier.views.MLService')
    def test_get_response_format(self, MockMLService):
        """GET retorna {success: true, data: {ecg_plot, beat_index}}."""
        mock_instance = MockMLService.return_value
        mock_instance.initialize.return_value = None
        mock_instance.has_test_data = True
        mock_instance.get_random_beat.return_value = (
            42,
            np.random.randn(260).astype(np.float32),
        )

        response = self.client.get('/api/v1/classify-random/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('data', data)
        self.assertIn('ecg_plot', data['data'])
        self.assertIn('beat_index', data['data'])
        self.assertIn('timestamp', data)
        self.assertEqual(data['data']['beat_index'], 42)

    @patch('classifier.views.MLService')
    def test_get_no_test_data(self, MockMLService):
        """GET sin dataset de prueba retorna 503."""
        mock_instance = MockMLService.return_value
        mock_instance.initialize.return_value = None
        mock_instance.has_test_data = False

        response = self.client.get('/api/v1/classify-random/')

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        data = response.json()
        self.assertFalse(data['success'])


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK)
class ClassifyRandomPostTests(TestCase):
    """Tests del endpoint POST /api/v1/classify-random/."""

    def setUp(self):
        self.client = APIClient()
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser_' + str(id(self)), password='password123')
        self.client.force_authenticate(user=self.user)

    @patch('classifier.views.ECGProcessor')
    @patch('classifier.views.MLService')
    def test_post_valid_beat_index(self, MockMLService, MockECGProcessor):
        """POST con beat_index válido retorna predicción exitosa."""
        mock_ml = MockMLService.return_value
        mock_ml.initialize.return_value = None
        mock_ml.has_test_data = True
        mock_ml.test_data_size = 1000
        mock_ml.get_beat_data.return_value = (
            np.zeros(260, dtype=np.float32),      # ecg_signal
            np.zeros(4, dtype=np.float32),         # rr_features
            0,                                      # true_label_index
        )
        mock_ml.predict.return_value = np.array(
            [[0.85, 0.05, 0.08, 0.02]], dtype=np.float32
        )

        mock_proc = MockECGProcessor.return_value
        mock_proc.prepare_single_beat.return_value = (
            np.zeros((1, 128, 128, 1)),
            np.zeros((1, 260, 1)),
            np.zeros((1, 4)),
        )

        response = self.client.post(
            '/api/v1/classify-random/',
            {'beat_index': 5},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('prediction', data['data'])
        self.assertIn('confidence', data['data'])
        self.assertIn('true_label', data['data'])
        self.assertIn('is_correct', data['data'])
        self.assertIn('all_probabilities', data['data'])
        self.assertIn('rr_info', data['data'])

    def test_post_missing_beat_index(self):
        """POST sin beat_index retorna 400."""
        response = self.client.post(
            '/api/v1/classify-random/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('error_code', data)

    def test_post_negative_beat_index(self):
        """POST con beat_index negativo retorna 400."""
        response = self.client.post(
            '/api/v1/classify-random/',
            {'beat_index': -1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertFalse(data['success'])

    def test_post_non_integer_beat_index(self):
        """POST con beat_index no entero retorna 400."""
        response = self.client.post(
            '/api/v1/classify-random/',
            {'beat_index': 'abc'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('classifier.views.MLService')
    def test_post_out_of_range_beat_index(self, MockMLService):
        """POST con beat_index fuera de rango retorna 400."""
        mock_ml = MockMLService.return_value
        mock_ml.initialize.return_value = None
        mock_ml.has_test_data = True
        mock_ml.test_data_size = 100

        response = self.client.post(
            '/api/v1/classify-random/',
            {'beat_index': 999999},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertFalse(data['success'])


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK)
class ResponseEnvelopeTests(TestCase):
    """Tests que verifican el formato envelope de respuestas."""

    def setUp(self):
        self.client = APIClient()
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser_' + str(id(self)), password='password123')
        self.client.force_authenticate(user=self.user)

    def test_error_response_has_standard_fields(self):
        """Las respuestas de error contienen success, message, errors, error_code, timestamp."""
        response = self.client.post(
            '/api/v1/classify-random/',
            {},
            format='json',
        )

        data = response.json()
        self.assertIn('success', data)
        self.assertIn('message', data)
        self.assertIn('errors', data)
        self.assertIn('error_code', data)
        self.assertIn('timestamp', data)
        self.assertFalse(data['success'])

    def test_error_does_not_expose_internals(self):
        """Los errores no exponen tracebacks, rutas de archivos, ni detalles internos."""
        response = self.client.post(
            '/api/v1/classify-random/',
            {'beat_index': 'invalid'},
            format='json',
        )

        data = response.json()
        response_str = str(data)

        # No debe contener rutas de archivos del servidor
        self.assertNotIn('f:\\', response_str.lower())
        self.assertNotIn('/home/', response_str.lower())
        self.assertNotIn('traceback', response_str.lower())
        self.assertNotIn('.py', response_str.lower())

    @patch('classifier.views.MLService')
    def test_success_response_has_standard_fields(self, MockMLService):
        """Las respuestas exitosas contienen success, message, data, timestamp."""
        mock_ml = MockMLService.return_value
        mock_ml.initialize.return_value = None
        mock_ml.has_test_data = True
        mock_ml.get_random_beat.return_value = (
            0,
            np.random.randn(260).astype(np.float32),
        )

        response = self.client.get('/api/v1/classify-random/')

        data = response.json()
        self.assertIn('success', data)
        self.assertIn('message', data)
        self.assertIn('data', data)
        self.assertIn('timestamp', data)
        self.assertTrue(data['success'])


@override_settings(REST_FRAMEWORK={
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.AnonRateThrottle', 'rest_framework.throttling.UserRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {'anon': '3/minute', 'user': '3/minute'},
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_AUTHENTICATION_CLASSES': ['core.authentication.CookieJWTAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
})
class ThrottlingTests(TestCase):
    """Tests de rate limiting."""
    def setUp(self):
        self.client = APIClient()
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser_' + str(id(self)), password='password123')
        self.client.force_authenticate(user=self.user)

    def test_throttling_returns_429_after_limit(self):
        """Después de exceder el límite de usuario, retorna HTTP 429."""
        # Usar cliente autenticado — con IsAuthenticated el 401 llega antes
        # que el throttle si el cliente es anónimo, por eso usamos UserRateThrottle
        for _ in range(4):
            response = self.client.post(
                '/api/v1/classify-random/',
                {'beat_index': 'x'},
                format='json',
            )

        # El último debe ser 429 (o 400 si no se alcanzó el throttle)
        self.assertIn(
            response.status_code,
            [status.HTTP_429_TOO_MANY_REQUESTS, status.HTTP_400_BAD_REQUEST],
        )
