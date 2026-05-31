"""
Tests de la capa de servicios — MLService, ECGProcessor, FileService, VisualizationService.

MLService requiere TensorFlow + modelo real, por lo que se mockea en la mayoría de
tests. Los tests de FileService y VisualizationService son puros (sin mocks).
"""

import base64
import os
import tempfile
from unittest.mock import patch, MagicMock

import numpy as np
from django.test import TestCase, override_settings

from classifier.constants import (
    LEN_SIGNAL, LEN_RR, IMG_SIZE, LABELS_MAP,
    ALLOWED_ECG_EXTENSIONS, PREMATURE_BEAT_THRESHOLD,
)
from classifier.services.ecg_processor import ECGProcessor
from classifier.services.file_service import FileService
from classifier.services.visualization_service import VisualizationService
from core.exceptions import FileValidationError


# ---------------------------------------------------------------------------
# MLService Tests
# ---------------------------------------------------------------------------

class MLServiceSingletonTests(TestCase):
    """Tests del patrón Singleton de MLService."""

    def test_singleton_returns_same_instance(self):
        """Dos llamadas a MLService() retornan el mismo objeto."""
        from classifier.services.ml_service import MLService
        a = MLService()
        b = MLService()
        self.assertIs(a, b)

    def test_not_initialized_by_default(self):
        """Antes de initialize(), is_ready debe ser False."""
        from classifier.services.ml_service import MLService
        service = MLService()
        # Si ya se inicializó en otro test, lo reseteamos
        if not service._initialized:
            self.assertFalse(service.is_ready)

    def test_predict_without_init_raises(self):
        """predict() sin initialize() lanza MLModelNotAvailableError."""
        from classifier.services.ml_service import MLService
        from core.exceptions import MLModelNotAvailableError

        service = MLService()
        # Forzar estado no inicializado para este test
        original_init = service._initialized
        original_model = service._model
        try:
            service._initialized = False
            service._model = None
            with self.assertRaises(MLModelNotAvailableError):
                dummy = np.zeros((1, IMG_SIZE, IMG_SIZE, 1))
                service.predict(dummy, np.zeros((1, LEN_SIGNAL, 1)), np.zeros((1, LEN_RR)))
        finally:
            # Restaurar estado original
            service._initialized = original_init
            service._model = original_model


class MLServicePredictSingleTests(TestCase):
    """Tests de predict_single() con modelo mockeado."""

    def test_predict_single_output_format(self):
        """predict_single() retorna dict con keys esperadas."""
        from classifier.services.ml_service import MLService

        service = MLService()

        # Mock del modelo
        mock_probs = np.array([[0.85, 0.05, 0.08, 0.02]], dtype=np.float32)
        with patch.object(service, '_model') as mock_model, \
             patch.object(service, '_initialized', True):
            mock_model.predict.return_value = mock_probs
            # Necesitamos que is_ready retorne True
            service._model = mock_model
            service._initialized = True

            cwt = np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.float32)
            sig = np.zeros(LEN_SIGNAL, dtype=np.float32)
            rr = np.zeros(LEN_RR, dtype=np.float32)

            result = service.predict_single(cwt, sig, rr)

            self.assertIn('pred_index', result)
            self.assertIn('pred_label', result)
            self.assertIn('confidence', result)
            self.assertIn('all_probabilities', result)
            self.assertEqual(result['pred_index'], 0)
            self.assertEqual(result['pred_label'], LABELS_MAP[0])
            self.assertAlmostEqual(result['confidence'], 85.0, places=1)


# ---------------------------------------------------------------------------
# ECGProcessor Tests
# ---------------------------------------------------------------------------

class ECGProcessorTests(TestCase):
    """Tests del servicio ECGProcessor."""

    def test_prepare_single_beat_shapes(self):
        """prepare_single_beat() retorna shapes correctas para modelo tri-modal."""
        processor = ECGProcessor()
        ecg = np.random.randn(LEN_SIGNAL).astype(np.float32)
        rr = np.random.randn(LEN_RR).astype(np.float32)

        cwt, sig, rr_out = processor.prepare_single_beat(ecg, rr)

        self.assertEqual(cwt.shape, (1, IMG_SIZE, IMG_SIZE, 1))
        self.assertEqual(sig.shape, (1, LEN_SIGNAL, 1))
        self.assertEqual(rr_out.shape, (1, LEN_RR))

    def test_prepare_batch_shapes(self):
        """prepare_batch() retorna shapes correctas para N latidos."""
        processor = ECGProcessor()
        n_beats = 5
        beats = [np.random.randn(LEN_SIGNAL).astype(np.float32) for _ in range(n_beats)]
        r_peaks = np.array([100, 460, 820, 1180, 1540])

        cwt, sig, rr = processor.prepare_batch(beats, r_peaks, sampling_rate=360)

        self.assertEqual(cwt.shape, (n_beats, IMG_SIZE, IMG_SIZE, 1))
        self.assertEqual(sig.shape, (n_beats, LEN_SIGNAL, 1))
        self.assertEqual(rr.shape, (n_beats, LEN_RR))

    def test_build_analysis_results_structure(self):
        """build_analysis_results() retorna estructura correcta."""
        processor = ECGProcessor()

        preds = np.array([0, 0, 1, 2])
        probs = np.array([
            [0.9, 0.05, 0.03, 0.02],
            [0.85, 0.1, 0.03, 0.02],
            [0.1, 0.8, 0.05, 0.05],
            [0.05, 0.05, 0.85, 0.05],
        ])
        rr_inputs = np.random.randn(4, LEN_RR).astype(np.float32)
        datos = {
            'r_peaks': [100, 460, 820, 1180],
        }

        result = processor.build_analysis_results(preds, probs, rr_inputs, datos)

        self.assertIn('estadisticas', result)
        self.assertIn('latidos', result)
        self.assertIn('total_predicciones', result)
        self.assertEqual(result['total_predicciones'], 4)
        self.assertIn('conteo', result['estadisticas'])
        self.assertIn('porcentaje', result['estadisticas'])

    def test_build_analysis_results_with_ground_truth(self):
        """Con ground-truth disponible, calcula accuracy."""
        processor = ECGProcessor()

        preds = np.array([0, 0, 1])
        probs = np.array([
            [0.9, 0.05, 0.03, 0.02],
            [0.85, 0.1, 0.03, 0.02],
            [0.1, 0.8, 0.05, 0.05],
        ])
        rr_inputs = np.random.randn(3, LEN_RR).astype(np.float32)
        datos = {
            'r_peaks': [100, 460, 820],
            'beat_classes': [0, 1, 1],  # ground truth
            'beat_symbols': ['N', 'A', 'A'],
        }

        result = processor.build_analysis_results(preds, probs, rr_inputs, datos)

        self.assertIn('accuracy', result)
        # pred[0]=0 == gt[0]=0 ✅, pred[1]=0 != gt[1]=1 ❌, pred[2]=1 == gt[2]=1 ✅
        # accuracy = 2/3 * 100 = 66.67
        self.assertAlmostEqual(result['accuracy'], 66.67, places=2)

    def test_build_analysis_results_max_beats(self):
        """max_beats limita el número de latidos en detalle."""
        processor = ECGProcessor()

        preds = np.array([0, 0, 0, 0, 0])
        probs = np.random.rand(5, 4).astype(np.float32)
        rr_inputs = np.random.randn(5, LEN_RR).astype(np.float32)
        datos = {'r_peaks': [100, 460, 820, 1180, 1540]}

        result = processor.build_analysis_results(
            preds, probs, rr_inputs, datos, max_beats=2
        )

        self.assertEqual(len(result['latidos']), 2)
        self.assertEqual(result['total_predicciones'], 5)


# ---------------------------------------------------------------------------
# FileService Tests
# ---------------------------------------------------------------------------

class FileServiceValidationTests(TestCase):
    """Tests de validación de archivos ECG."""

    def _make_uploaded_file(self, name, size=100):
        """Helper para crear un UploadedFile mock."""
        mock_file = MagicMock()
        mock_file.name = name
        mock_file.size = size
        return mock_file

    def test_valid_dat_file(self):
        """Un archivo .dat válido pasa la validación."""
        uploaded = self._make_uploaded_file('100.dat', size=1000)
        result = FileService.validate_ecg_file(uploaded)
        self.assertEqual(result, '100.dat')

    def test_valid_hea_file(self):
        """Un archivo .hea válido pasa la validación."""
        uploaded = self._make_uploaded_file('100.hea', size=500)
        result = FileService.validate_ecg_file(uploaded)
        self.assertEqual(result, '100.hea')

    def test_valid_atr_file(self):
        """Un archivo .atr válido pasa la validación."""
        uploaded = self._make_uploaded_file('100.atr', size=500)
        result = FileService.validate_ecg_file(uploaded)
        self.assertEqual(result, '100.atr')

    def test_invalid_extension_rejected(self):
        """Extensiones no permitidas (.exe, .py, .txt) lanzan FileValidationError."""
        for ext in ['.exe', '.py', '.txt', '.zip', '.js']:
            uploaded = self._make_uploaded_file(f'malicious{ext}')
            with self.assertRaises(FileValidationError, msg=f"Extension {ext} should be rejected"):
                FileService.validate_ecg_file(uploaded)

    def test_path_traversal_rejected(self):
        """Nombres con path traversal lanzan FileValidationError."""
        dangerous_names = [
            '../../etc/passwd.dat',
            '..\\..\\windows\\system32\\config.dat',
            'subdir/file.dat',
        ]
        for name in dangerous_names:
            uploaded = self._make_uploaded_file(name)
            with self.assertRaises(FileValidationError, msg=f"Name '{name}' should be rejected"):
                FileService.validate_ecg_file(uploaded)

    def test_oversized_file_rejected(self):
        """Archivos mayores a MAX_ECG_FILE_SIZE_BYTES lanzan FileValidationError."""
        uploaded = self._make_uploaded_file(
            'huge.dat',
            size=60 * 1024 * 1024,  # 60MB > 50MB limit
        )
        with self.assertRaises(FileValidationError):
            FileService.validate_ecg_file(uploaded)


class FileServiceSessionTests(TestCase):
    """Tests de gestión de sesiones temporales."""

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_create_and_cleanup_session(self):
        """create_session() crea un directorio y cleanup_session() lo elimina."""
        session_id, session_dir = FileService.create_session()

        self.assertTrue(os.path.isdir(session_dir))
        self.assertTrue(len(session_id) > 0)

        FileService.cleanup_session(session_dir)

        self.assertFalse(os.path.exists(session_dir))

    def test_cleanup_nonexistent_dir_no_error(self):
        """cleanup_session() con directorio inexistente no lanza excepciones."""
        # No debe lanzar ninguna excepción
        FileService.cleanup_session('/nonexistent/path/abc123')

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_get_record_path(self):
        """get_record_path() construye ruta correctamente."""
        _, session_dir = FileService.create_session()
        path = FileService.get_record_path(session_dir, '100')
        self.assertTrue(path.endswith('100'))
        FileService.cleanup_session(session_dir)


# ---------------------------------------------------------------------------
# VisualizationService Tests
# ---------------------------------------------------------------------------

class VisualizationServiceTests(TestCase):
    """Tests del servicio de visualización."""

    def test_plot_returns_base64_string(self):
        """plot_ecg_to_base64() retorna un string base64 válido."""
        signal = np.random.randn(260).astype(np.float32)
        result = VisualizationService.plot_ecg_to_base64(signal)

        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_plot_is_valid_base64(self):
        """El string retornado es decodeable como base64."""
        signal = np.random.randn(260).astype(np.float32)
        result = VisualizationService.plot_ecg_to_base64(signal)

        # Debe poder decodear sin error
        decoded = base64.b64decode(result)
        # Debe ser un PNG (magic bytes)
        self.assertTrue(decoded[:4] == b'\x89PNG')

    def test_plot_with_custom_title(self):
        """Funciona con título customizado."""
        signal = np.random.randn(260).astype(np.float32)
        result = VisualizationService.plot_ecg_to_base64(
            signal, title='Test Plot', sampling_rate=250
        )
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_plot_short_signal(self):
        """Funciona con señales cortas."""
        signal = np.random.randn(50).astype(np.float32)
        result = VisualizationService.plot_ecg_to_base64(signal)
        self.assertIsInstance(result, str)
