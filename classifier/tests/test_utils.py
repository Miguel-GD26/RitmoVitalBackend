"""
Tests unitarios para classifier.utils — funciones de bajo nivel del pipeline ECG.

Verifica CWT, features RR, filtro bandpass, corrección de R-peaks y detección
automática, sin necesidad de modelo TensorFlow ni acceso a archivos.
"""

import numpy as np
from django.test import TestCase

from classifier.utils import (
    apply_cwt,
    calculate_rr_features,
    bandpass_filter,
    correct_r_peaks,
    detect_r_peaks_automatic,
)
from classifier.constants import WINDOW_SIZE, CWT_SIZE


class ApplyCwtTests(TestCase):
    """Tests para la función apply_cwt()."""

    def test_output_shape(self):
        """El escalograma CWT debe tener shape (128, 128)."""
        signal = np.random.randn(WINDOW_SIZE).astype(np.float32)
        result = apply_cwt(signal)
        self.assertEqual(result.shape, (CWT_SIZE, CWT_SIZE))

    def test_output_dtype(self):
        """El escalograma debe ser float32."""
        signal = np.random.randn(WINDOW_SIZE).astype(np.float32)
        result = apply_cwt(signal)
        self.assertEqual(result.dtype, np.float32)

    def test_short_signal_padding(self):
        """Señales más cortas que WINDOW_SIZE se padean correctamente."""
        short_signal = np.random.randn(100).astype(np.float32)
        result = apply_cwt(short_signal)
        self.assertEqual(result.shape, (CWT_SIZE, CWT_SIZE))

    def test_normalization_range(self):
        """Los valores del escalograma deben estar en [0, 1]."""
        signal = np.random.randn(WINDOW_SIZE).astype(np.float32)
        result = apply_cwt(signal)
        self.assertGreaterEqual(result.min(), 0.0)
        self.assertLessEqual(result.max(), 1.0 + 1e-6)

    def test_zero_signal(self):
        """Una señal de ceros no debe causar error (edge case)."""
        signal = np.zeros(WINDOW_SIZE, dtype=np.float32)
        result = apply_cwt(signal)
        self.assertEqual(result.shape, (CWT_SIZE, CWT_SIZE))


class CalculateRrFeaturesTests(TestCase):
    """Tests para la función calculate_rr_features()."""

    def test_output_shape(self):
        """El output debe tener shape (N, 4) para N picos R."""
        r_peaks = np.array([100, 400, 700, 1000, 1300])
        result = calculate_rr_features(r_peaks, fs=360)
        self.assertEqual(result.shape, (5, 4))

    def test_output_dtype(self):
        """El output debe ser float32."""
        r_peaks = np.array([100, 400, 700])
        result = calculate_rr_features(r_peaks, fs=360)
        self.assertEqual(result.dtype, np.float32)

    def test_single_peak(self):
        """Con un solo pico R, debe retornar defaults razonables."""
        r_peaks = np.array([500])
        result = calculate_rr_features(r_peaks, fs=360)
        self.assertEqual(result.shape, (1, 4))
        # pre_rr y post_rr deben ser defaults (0.8)
        self.assertAlmostEqual(result[0, 0], 0.8, places=2)
        self.assertAlmostEqual(result[0, 1], 0.8, places=2)

    def test_two_peaks(self):
        """Con dos picos R, calcula intervalos correctamente."""
        r_peaks = np.array([0, 360])  # 1 segundo de distancia a 360 Hz
        result = calculate_rr_features(r_peaks, fs=360)
        self.assertEqual(result.shape, (2, 4))
        # Segundo pico: pre_rr = (360-0)/360 = 1.0s
        self.assertAlmostEqual(result[1, 0], 1.0, places=2)

    def test_list_input_accepted(self):
        """Acepta listas además de np.arrays."""
        r_peaks = [100, 400, 700]
        result = calculate_rr_features(r_peaks, fs=360)
        self.assertEqual(result.shape, (3, 4))

    def test_features_are_positive(self):
        """Todos los features RR deben ser no-negativos."""
        r_peaks = np.array([100, 400, 700, 1000, 1300])
        result = calculate_rr_features(r_peaks, fs=360)
        self.assertTrue(np.all(result >= 0))


class BandpassFilterTests(TestCase):
    """Tests para la función bandpass_filter()."""

    def test_output_length_preserved(self):
        """El filtro no cambia la longitud de la señal."""
        signal = np.random.randn(1000)
        result = bandpass_filter(signal, fs=360)
        self.assertEqual(len(result), len(signal))

    def test_output_is_float(self):
        """El output es un array de floats."""
        signal = np.random.randn(1000)
        result = bandpass_filter(signal, fs=360)
        self.assertTrue(np.issubdtype(result.dtype, np.floating))


class CorrectRPeaksTests(TestCase):
    """Tests para la función correct_r_peaks()."""

    def test_removes_close_peaks(self):
        """Elimina picos con RR < 200ms (a 360Hz = 72 muestras)."""
        # Picos a 0, 50 (muy cercano), 400, 800 muestras
        r_peaks = np.array([0, 50, 400, 800])
        result = correct_r_peaks(r_peaks, fs=360, min_rr_ms=200)
        # Debe eliminar el pico en 50 (demasiado cercano al de 0)
        self.assertNotIn(50, result)
        self.assertIn(0, result)
        self.assertIn(400, result)

    def test_single_peak_preserved(self):
        """Un solo pico se preserva."""
        r_peaks = np.array([500])
        result = correct_r_peaks(r_peaks, fs=360)
        self.assertEqual(len(result), 1)

    def test_empty_peaks(self):
        """Array vacío retorna array vacío."""
        r_peaks = np.array([])
        result = correct_r_peaks(r_peaks, fs=360)
        self.assertEqual(len(result), 0)

    def test_well_spaced_peaks_preserved(self):
        """Picos bien espaciados (>200ms) se preservan todos."""
        # Picos cada 360 muestras = 1s a 360Hz
        r_peaks = np.array([0, 360, 720, 1080])
        result = correct_r_peaks(r_peaks, fs=360)
        self.assertEqual(len(result), 4)


class DetectRPeaksAutomaticTests(TestCase):
    """Tests para la función detect_r_peaks_automatic()."""

    def test_returns_numpy_array(self):
        """Retorna un numpy array."""
        # Generar señal sintética con picos R evidentes
        fs = 360
        t = np.arange(0, 5, 1 / fs)
        # Señal sinusoidal con picos periódicos
        signal = np.sin(2 * np.pi * 1.2 * t)  # ~1.2 Hz ≈ 72 bpm
        result = detect_r_peaks_automatic(signal, fs)
        self.assertIsInstance(result, np.ndarray)

    def test_detects_peaks_in_synthetic_signal(self):
        """Detecta al menos 1 pico en una señal sintética."""
        fs = 360
        duration = 3  # 3 segundos
        t = np.arange(0, duration, 1 / fs)
        signal = np.sin(2 * np.pi * 1.0 * t)
        result = detect_r_peaks_automatic(signal, fs)
        self.assertGreater(len(result), 0)
