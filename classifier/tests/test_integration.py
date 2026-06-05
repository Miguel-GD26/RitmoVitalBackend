"""
classifier.tests.test_integration — Tests de integración del flujo ECG.

Prueba el camino completo:
  HTTP upload → FileService → Celery (eager) → Orchestrator
  → ECGReader (mocked) → ML (mocked) → DB → Cache → Poll

Los mocks se aplican en setUp para evitar repetición por test.
TensorFlow y wfdb NO se cargan — solo se prueba la coordinación de capas.
"""
import numpy as np
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from classifier.models import Paciente, AnalisisECG

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
}

TEST_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ecg_data(n=3, with_labels=True):
    """ECG sintético para mockear process_record_*."""
    data = {
        'beats': [np.zeros(260, dtype=np.float32) for _ in range(n)],
        'r_peaks': list(range(100, 100 + n * 360, 360)),
        'sampling_rate': 360,
        'signal': np.zeros(n * 360 + 200, dtype=np.float32),
        'total_beats_detected': n,
        'beats_excluded': 0,
        'excluded_symbols': {},
    }
    if with_labels:
        data['beat_classes'] = [0] * n
        data['beat_symbols'] = ['N'] * n
    return data


def _predictions(n=3):
    """Predicciones sintéticas: todas Normal (clase 0) con 90% confianza."""
    probs = np.zeros((n, 4), dtype=np.float32)
    probs[:, 0] = 0.90
    probs[:, 1] = 0.05
    probs[:, 2] = 0.03
    probs[:, 3] = 0.02
    return (
        np.zeros(n, dtype=np.int64),
        probs,
        np.zeros((n, 4), dtype=np.float32),
    )


def _files(record='100', annotated=True):
    """Archivos ECG mínimos para upload multipart."""
    f = {
        'dat_file': SimpleUploadedFile(f'{record}.dat', b'\x00' * 512, 'application/octet-stream'),
        'hea_file': SimpleUploadedFile(f'{record}.hea', b'\x00' * 128, 'application/octet-stream'),
    }
    if annotated:
        f['atr_file'] = SimpleUploadedFile(f'{record}.atr', b'\x00' * 256, 'application/octet-stream')
    return f


# ---------------------------------------------------------------------------
# Base TestCase
# ---------------------------------------------------------------------------

@override_settings(
    REST_FRAMEWORK=TEST_REST_FRAMEWORK,
    CACHES=TEST_CACHE,
    CLOUDINARY_ENABLED=False,
)
class BaseECGIntegrationTest(TestCase):
    """
    Configura usuario médico, paciente de prueba y mocks de servicios ML/ECG.
    Los tests heredan esta clase para evitar repetir la infraestructura de mock.
    """

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='medico_integ', email='medico@integ.test', password='Pass123!'
        )
        group, _ = Group.objects.get_or_create(name='investigador')
        self.user.groups.add(group)
        self.client.force_authenticate(user=self.user)

        self.paciente = Paciente.objects.create(
            nombre='Paciente', apellido='Integración', creado_por=self.user
        )

        # Mocks comunes a todos los tests
        self._start_patch('classifier.services.analysis_orchestrator._get_ml_backend',
                          side_effect=self._ml_backend_factory)
        self._start_patch('classifier.services.ecg_processor.ECGProcessor.process_record_with_annotations',
                          return_value=_ecg_data(n=3, with_labels=True))
        self._start_patch('classifier.services.ecg_processor.ECGProcessor.process_record_production',
                          return_value=_ecg_data(n=3, with_labels=False))
        self._start_patch('classifier.services.ecg_processor.ECGProcessor.predict_chunked',
                          return_value=_predictions(n=3))
        self._start_patch('classifier.services.visualization_service.VisualizationService.plot_ecg_to_cloudinary',
                          return_value=None)
        self._start_patch('classifier.services.visualization_service.VisualizationService.plot_ecg_to_base64',
                          return_value='iVBORw0KGgoAAAANSUhEUg==')

    def _start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _ml_backend_factory():
        ml = MagicMock()
        ml.version = 'test_model@abc12345'
        ml.is_ready = True
        return ml

    def _submit_annotated(self, record='100', page_size=100):
        return self.client.post(
            f'/api/v1/analyze-patient/?page=1&page_size={page_size}',
            _files(record, annotated=True),
            format='multipart',
        )

    def _submit_production(self, record='100', page_size=100):
        return self.client.post(
            f'/api/v1/analyze-patient-production/?page=1&page_size={page_size}',
            _files(record, annotated=False),
            format='multipart',
        )

    def _poll(self, task_id):
        return self.client.get(f'/api/v1/analysis/status/{task_id}/')


# ---------------------------------------------------------------------------
# Flujo anotado
# ---------------------------------------------------------------------------

class AnnotatedAnalysisFlowTests(BaseECGIntegrationTest):
    """Flujo .dat + .atr + .hea → análisis con ground-truth."""

    def test_submit_returns_task_id_and_pending_status(self):
        resp = self._submit_annotated()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()['data']
        self.assertIn('task_id', data)
        self.assertEqual(data['status'], 'pending')

    def test_task_completes_with_correct_structure(self):
        """Con CELERY_TASK_ALWAYS_EAGER=True el task completa antes del poll."""
        task_id = self._submit_annotated().json()['data']['task_id']
        resp = self._poll(task_id)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payload = resp.json()
        self.assertEqual(payload['data']['status'], 'completed')

        result = payload['data']['result']
        self.assertEqual(result['record_name'], '100')
        self.assertIn('accuracy', result)
        self.assertIn('estadisticas', result)
        self.assertIn('total_latidos', result)
        self.assertIn('latidos_procesados', result)

    def test_task_result_has_valid_accuracy(self):
        task_id = self._submit_annotated().json()['data']['task_id']
        result = self._poll(task_id).json()['data']['result']
        acc = result.get('accuracy')
        self.assertIsNotNone(acc)
        self.assertGreaterEqual(acc, 0.0)
        self.assertLessEqual(acc, 100.0)

    def test_analysis_saved_to_database(self):
        before = AnalisisECG.objects.filter(usuario=self.user).count()
        self._submit_annotated()
        after = AnalisisECG.objects.filter(usuario=self.user).count()
        self.assertEqual(after, before + 1)

        analisis = AnalisisECG.objects.filter(usuario=self.user).latest('fecha')
        self.assertEqual(analisis.modo, 'anotado')
        self.assertEqual(analisis.record_name, '100')
        self.assertEqual(analisis.usuario, self.user)

    def test_analysis_linked_to_patient_when_paciente_id_provided(self):
        resp = self.client.post(
            '/api/v1/analyze-patient/?page=1&page_size=100',
            {**_files('100', annotated=True), 'paciente_id': str(self.paciente.id)},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        analisis = AnalisisECG.objects.filter(usuario=self.user).latest('fecha')
        self.assertEqual(analisis.paciente, self.paciente)

    def test_task_has_pagination_metadata(self):
        task_id = self._submit_annotated().json()['data']['task_id']
        resp = self._poll(task_id)
        self.assertIn('pagination', resp.json())

    def test_unknown_task_id_returns_404(self):
        resp = self._poll('taskidquenuncaexistio12345')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(resp.json()['success'])


# ---------------------------------------------------------------------------
# Validaciones de archivo (sin mocks de ML — fallan antes de llegar al pipeline)
# ---------------------------------------------------------------------------

@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK, CACHES=TEST_CACHE, CLOUDINARY_ENABLED=False)
class FileValidationTests(TestCase):
    """Tests de validación de archivos ECG — no necesitan mocks ML."""

    def setUp(self):
        self.client = APIClient()
        user = User.objects.create_user(username='medico_val', email='val@test.com', password='Pass!')
        group, _ = Group.objects.get_or_create(name='investigador')
        user.groups.add(group)
        self.client.force_authenticate(user=user)

    def test_pacemaker_record_102_rejected(self):
        resp = self.client.post(
            '/api/v1/analyze-patient/?page=1&page_size=100',
            _files('102', annotated=True),
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.json()['success'])
        self.assertIn('marcapasos', str(resp.json()).lower())

    def test_pacemaker_record_104_rejected(self):
        resp = self.client.post(
            '/api/v1/analyze-patient/?page=1&page_size=100',
            _files('104', annotated=True),
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pacemaker_record_107_rejected_production(self):
        resp = self.client.post(
            '/api/v1/analyze-patient-production/?page=1&page_size=100',
            _files('107', annotated=False),
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_extension_dat_rejected(self):
        resp = self.client.post(
            '/api/v1/analyze-patient/?page=1&page_size=100',
            {
                'dat_file': SimpleUploadedFile('100.exe', b'X' * 100),
                'hea_file': SimpleUploadedFile('100.hea', b'X' * 100),
                'atr_file': SimpleUploadedFile('100.atr', b'X' * 100),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_dat_file_rejected(self):
        resp = self.client.post(
            '/api/v1/analyze-patient/?page=1&page_size=100',
            {
                'hea_file': SimpleUploadedFile('100.hea', b'X' * 100),
                'atr_file': SimpleUploadedFile('100.atr', b'X' * 100),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_atr_file_rejected_annotated(self):
        resp = self.client.post(
            '/api/v1/analyze-patient/?page=1&page_size=100',
            {
                'dat_file': SimpleUploadedFile('100.dat', b'X' * 100),
                'hea_file': SimpleUploadedFile('100.hea', b'X' * 100),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_file_rejected(self):
        resp = self.client.post(
            '/api/v1/analyze-patient/?page=1&page_size=100',
            {
                'dat_file': SimpleUploadedFile('100.dat', b'X' * (51 * 1024 * 1024)),
                'hea_file': SimpleUploadedFile('100.hea', b'X' * 100),
                'atr_file': SimpleUploadedFile('100.atr', b'X' * 100),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_analysis_requires_authentication(self):
        client = APIClient()
        resp = client.post(
            '/api/v1/analyze-patient/?page=1&page_size=100',
            _files('100', annotated=True),
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Flujo de producción
# ---------------------------------------------------------------------------

class ProductionAnalysisFlowTests(BaseECGIntegrationTest):
    """Flujo .dat + .hea sin anotaciones → detección automática de R-peaks."""

    def test_production_submit_returns_task_id(self):
        resp = self._submit_production()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('task_id', resp.json()['data'])

    def test_production_result_has_no_accuracy(self):
        task_id = self._submit_production().json()['data']['task_id']
        result = self._poll(task_id).json()['data']['result']
        self.assertEqual(self._poll(task_id).json()['data']['status'], 'completed')
        self.assertNotIn('accuracy', result)
        self.assertIn('estadisticas', result)
        self.assertIn('total_latidos', result)

    def test_production_analysis_saved_with_correct_mode(self):
        before = AnalisisECG.objects.filter(usuario=self.user, modo='produccion').count()
        self._submit_production()
        after = AnalisisECG.objects.filter(usuario=self.user, modo='produccion').count()
        self.assertEqual(after, before + 1)
