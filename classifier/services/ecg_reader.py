"""
classifier.services.ecg_reader — Lectura y segmentación de registros MIT-BIH.

Funciones para cargar archivos de registro ECG y extraer latidos:
- Modo anotado: lee archivo .atr para ground-truth
- Modo producción: detección automática de picos R
"""

import os

import numpy as np
import wfdb

from classifier.constants import AAMI_MAPPING, WINDOW_SIZE
from classifier.services.signal_processing import detect_r_peaks_automatic


def procesar_archivo_mitbih(ruta_base):
    """Lee registro MIT-BIH anotado y extrae latidos válidos según AAMI_MAPPING."""
    try:
        record = wfdb.rdrecord(ruta_base)
        annotation = wfdb.rdann(ruta_base, 'atr')
    except Exception as e:
        raise ValueError(f"Error al leer archivos MIT-BIH: {e}")

    signal = record.p_signal[:, 0]
    sampling_rate = record.fs
    r_peaks = annotation.sample
    beat_symbols = annotation.symbol

    beats, valid_symbols, valid_classes, valid_r_peaks = [], [], [], []
    total_beats = len(r_peaks)
    excluded_beats = 0
    excluded_symbols_count = {}

    window_before = WINDOW_SIZE // 2
    window_after = WINDOW_SIZE - window_before

    if np.std(signal) > 1e-6:
        signal = (signal - np.mean(signal)) / (np.std(signal) + 1e-8)

    for i, r_peak in enumerate(r_peaks):
        symbol = beat_symbols[i]
        clase_aami = AAMI_MAPPING.get(symbol, -2)

        if clase_aami in [-1, -2]:
            excluded_beats += 1
            excluded_symbols_count[symbol] = excluded_symbols_count.get(symbol, 0) + 1
            continue

        start = r_peak - window_before
        end = r_peak + window_after

        if start >= 0 and end <= len(signal):
            beat_segment = signal[start:end]
            if len(beat_segment) == WINDOW_SIZE:
                beats.append(beat_segment)
                valid_symbols.append(symbol)
                valid_classes.append(clase_aami)
                valid_r_peaks.append(r_peak)
            else:
                excluded_beats += 1
        else:
            excluded_beats += 1

    return {
        'record_name': os.path.basename(ruta_base),
        'signal': signal,
        'r_peaks': valid_r_peaks,
        'beats': beats,
        'beat_symbols': valid_symbols,
        'beat_classes': valid_classes,
        'sampling_rate': int(sampling_rate),
        'total_beats_detected': total_beats,
        'beats_excluded': excluded_beats,
        'beats_processed': len(beats),
        'excluded_symbols': excluded_symbols_count,
    }


def procesar_archivo_mitbih_produccion(ruta_base):
    """Lee registro ECG sin anotaciones y detecta latidos automáticamente (Pan-Tompkins)."""
    try:
        record = wfdb.rdrecord(ruta_base)
    except Exception as e:
        raise ValueError(f"Error al leer archivo de registro: {e}")

    signal = record.p_signal[:, 0]
    sampling_rate = record.fs
    r_peaks = detect_r_peaks_automatic(signal, fs=int(sampling_rate))

    beats, valid_r_peaks = [], []
    window_before = WINDOW_SIZE // 2
    window_after = WINDOW_SIZE - window_before

    if np.std(signal) > 1e-6:
        signal = (signal - np.mean(signal)) / (np.std(signal) + 1e-8)

    for r_peak in r_peaks:
        start = int(r_peak - window_before)
        end = int(r_peak + window_after)

        if start >= 0 and end <= len(signal):
            beat_segment = signal[start:end]
            if len(beat_segment) == WINDOW_SIZE:
                beats.append(beat_segment)
                valid_r_peaks.append(int(r_peak))

    return {
        'record_name': os.path.basename(ruta_base),
        'signal': signal,
        'r_peaks': valid_r_peaks,
        'beats': beats,
        'sampling_rate': int(sampling_rate),
        'total_beats_detected': len(valid_r_peaks),
    }
