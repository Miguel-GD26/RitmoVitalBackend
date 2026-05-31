"""
classifier.services.signal_processing — Transformaciones de señal ECG (CWT, RR-features, filtrado).
"""

import numpy as np
import cv2
import pywt
from ecgdetectors import Detectors
from scipy.signal import butter, filtfilt

from classifier.constants import WAVELET, CWT_SIZE, WINDOW_SIZE


def apply_cwt(signal, wavelet=WAVELET, output_size=CWT_SIZE):
    """CWT sobre señal 1D → escalograma 2D normalizado (output_size × output_size)."""
    if len(signal) < WINDOW_SIZE:
        pad_len = WINDOW_SIZE - len(signal)
        signal = np.pad(signal, (0, pad_len), 'constant')

    scales = np.arange(1, 65)
    coefficients, _ = pywt.cwt(signal, scales, wavelet)
    coefficients = np.abs(coefficients)

    resized_coefficients = cv2.resize(
        coefficients,
        (output_size, output_size),
        interpolation=cv2.INTER_CUBIC,
    )

    min_val = np.min(resized_coefficients)
    max_val = np.max(resized_coefficients)

    if max_val > min_val:
        resized_coefficients = (resized_coefficients - min_val) / (max_val - min_val + 1e-8)

    return resized_coefficients.astype(np.float32)


def calculate_rr_features(r_peaks, fs):
    """Retorna array (N, 4) con features [pre_rr, post_rr, pre_ratio, post_ratio] por pico R."""
    if not isinstance(r_peaks, np.ndarray):
        r_peaks = np.array(r_peaks)

    rr_list = []
    num_peaks = len(r_peaks)

    for i in range(num_peaks):
        pre_rr = (r_peaks[i] - r_peaks[i - 1]) / fs if i > 0 else 0.8
        post_rr = (r_peaks[i + 1] - r_peaks[i]) / fs if i < num_peaks - 1 else 0.8

        start_avg = max(0, i - 10)
        if i > start_avg:
            local_rrs = np.diff(r_peaks[start_avg: i + 1]) / fs
            local_avg = np.mean(local_rrs) if len(local_rrs) > 0 else 0.8
        else:
            local_avg = 0.8

        safe_avg = local_avg if local_avg > 1e-5 else 0.8
        pre_ratio = pre_rr / safe_avg
        post_ratio = post_rr / safe_avg

        rr_list.append([pre_rr, post_rr, pre_ratio, post_ratio])

    return np.array(rr_list, dtype=np.float32)


def bandpass_filter(signal, fs, lowcut=5.0, highcut=15.0, order=1):
    """Filtro Butterworth pasabanda orden `order` entre lowcut–highcut Hz."""
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    return filtfilt(b, a, signal)


def correct_r_peaks(r_peaks, fs, min_rr_ms=200):
    """Elimina picos R con intervalo < min_rr_ms ms (eliminación de detecciones dobles)."""
    if len(r_peaks) < 2:
        return r_peaks

    rr_intervals_ms = np.diff(r_peaks) * 1000 / fs
    corrected_peaks = [r_peaks[0]]

    for i, rr in enumerate(rr_intervals_ms):
        if rr >= min_rr_ms:
            corrected_peaks.append(r_peaks[i + 1])

    return np.array(corrected_peaks)


def detect_r_peaks_automatic(signal, fs):
    """Pan-Tompkins R-peak detection + corrección de dobles detecciones."""
    filtered_signal = bandpass_filter(signal.astype(np.float64), fs)
    detectors = Detectors(fs)
    initial_r_peaks = detectors.pan_tompkins_detector(filtered_signal)
    return correct_r_peaks(np.array(initial_r_peaks), fs)
