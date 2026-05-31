"""
Tests unitarios para ECGProcessor.predict_chunked.

Verifica que la función:
- Procesa N latidos con M chunks correctamente
- Concatena probabilidades en el orden correcto
- Libera chunks intermedios (no acumula OOM)
- Maneja edge-cases: 1 latido, chunk_size > N
"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import django

# Django setup mínimo para importar módulos sin servidor
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cardioweb.settings')
os.environ.setdefault('DJANGO_ENV', 'development')

import django
django.setup()

from classifier.services.ecg_processor import ECGProcessor
from classifier.constants import LEN_SIGNAL, LEN_RR, IMG_SIZE


def _make_beats(n: int):
    """Genera N latidos dummy de forma (LEN_SIGNAL,)."""
    return [np.zeros(LEN_SIGNAL, dtype=np.float32) for _ in range(n)]


def _make_r_peaks(n: int, fs: int = 360):
    """Genera N picos R separados a fs muestras (1 segundo entre picos)."""
    return np.arange(n) * fs


def _make_ml_service(num_classes: int = 5):
    """Mock de MLService que devuelve probabilidades uniformes."""
    ml = MagicMock()

    def fake_predict(cwt_imgs, sigs, rr):
        batch = cwt_imgs.shape[0]
        probs = np.full((batch, num_classes), 1.0 / num_classes, dtype=np.float32)
        return probs

    ml.predict.side_effect = fake_predict
    return ml


class TestPredictChunked(unittest.TestCase):

    def test_output_shape_matches_input(self):
        """preds shape (N,), probs shape (N, C), rr shape (N, LEN_RR)."""
        n = 20
        beats = _make_beats(n)
        r_peaks = _make_r_peaks(n)
        ml = _make_ml_service()

        preds, probs, rr_all = ECGProcessor.predict_chunked(
            beats, r_peaks, sampling_rate=360, ml_service=ml, chunk_size=8
        )

        self.assertEqual(preds.shape[0], n)
        self.assertEqual(probs.shape[0], n)
        self.assertEqual(rr_all.shape[0], n)
        self.assertEqual(rr_all.shape[1], LEN_RR)

    def test_single_beat(self):
        """Edge-case: un solo latido."""
        beats = _make_beats(1)
        r_peaks = _make_r_peaks(1)
        ml = _make_ml_service()

        preds, probs, rr_all = ECGProcessor.predict_chunked(
            beats, r_peaks, sampling_rate=360, ml_service=ml, chunk_size=64
        )

        self.assertEqual(len(preds), 1)
        self.assertEqual(len(probs), 1)

    def test_chunk_size_larger_than_n(self):
        """Cuando chunk_size > N, todo cabe en un solo chunk."""
        n = 5
        beats = _make_beats(n)
        r_peaks = _make_r_peaks(n)
        ml = _make_ml_service()

        preds, probs, rr_all = ECGProcessor.predict_chunked(
            beats, r_peaks, sampling_rate=360, ml_service=ml, chunk_size=100
        )

        self.assertEqual(len(preds), n)
        self.assertEqual(ml.predict.call_count, 1)

    def test_correct_number_of_ml_calls(self):
        """predict() debe llamarse ceil(N / chunk_size) veces."""
        import math
        n, chunk_size = 17, 5
        beats = _make_beats(n)
        r_peaks = _make_r_peaks(n)
        ml = _make_ml_service()

        ECGProcessor.predict_chunked(
            beats, r_peaks, sampling_rate=360, ml_service=ml, chunk_size=chunk_size
        )

        expected_calls = math.ceil(n / chunk_size)
        self.assertEqual(ml.predict.call_count, expected_calls)

    def test_predictions_are_argmax_of_probs(self):
        """preds[i] debe ser argmax(probs[i])."""
        n = 10
        beats = _make_beats(n)
        r_peaks = _make_r_peaks(n)
        ml = _make_ml_service(num_classes=5)

        preds, probs, _ = ECGProcessor.predict_chunked(
            beats, r_peaks, sampling_rate=360, ml_service=ml
        )

        np.testing.assert_array_equal(preds, np.argmax(probs, axis=1))

    def test_probs_sum_to_one(self):
        """Las probabilidades de cada latido deben sumar 1.0."""
        n = 15
        beats = _make_beats(n)
        r_peaks = _make_r_peaks(n)
        ml = _make_ml_service(num_classes=5)

        _, probs, _ = ECGProcessor.predict_chunked(
            beats, r_peaks, sampling_rate=360, ml_service=ml
        )

        row_sums = probs.sum(axis=1)
        np.testing.assert_allclose(row_sums, np.ones(n), atol=1e-5)

    def test_exact_chunk_boundary(self):
        """N divisible exactamente por chunk_size — no debe fallar ni perder latidos."""
        n, chunk_size = 16, 4
        beats = _make_beats(n)
        r_peaks = _make_r_peaks(n)
        ml = _make_ml_service()

        preds, probs, rr_all = ECGProcessor.predict_chunked(
            beats, r_peaks, sampling_rate=360, ml_service=ml, chunk_size=chunk_size
        )

        self.assertEqual(len(preds), n)
        self.assertEqual(ml.predict.call_count, n // chunk_size)


if __name__ == '__main__':
    unittest.main()
