"""
classifier.services.ecg_processor — Preparación de señales ECG para inferencia tri-modal.
"""

import gc
import logging
import os
from concurrent.futures import ThreadPoolExecutor

# Cap CWT parallelism to avoid thread-contention on Railway Starter (2 vCPUs).
# With 2 concurrent analyses each spawning 8 threads + 8 Gunicorn threads =
# 24 threads for 2 vCPUs. This constant limits it to a safe ceiling.
_CWT_MAX_WORKERS = min(4, os.cpu_count() or 2)

import numpy as np

from classifier.services.signal_processing import apply_cwt, calculate_rr_features
from classifier.services.ecg_reader import (
    procesar_archivo_mitbih,
    procesar_archivo_mitbih_produccion,
)
from classifier.constants import LEN_SIGNAL, LEN_RR, IMG_SIZE, LABELS_MAP

logger = logging.getLogger(__name__)


class ECGProcessor:
    """Servicio stateless para procesamiento de señales ECG."""

    # ------------------------------------------------------------------
    # Preparación de inputs para inferencia
    # ------------------------------------------------------------------

    @staticmethod
    def prepare_single_beat(ecg_signal, rr_features):
        """Retorna (cwt_image, signal_input, rr_input) listos para model.predict()."""
        scalogram = apply_cwt(ecg_signal).reshape(1, IMG_SIZE, IMG_SIZE, 1)
        signal_input = ecg_signal.reshape(1, LEN_SIGNAL, 1)
        rr_input = rr_features.reshape(1, LEN_RR)
        return scalogram, signal_input, rr_input

    @staticmethod
    def prepare_batch(beats, r_peaks, sampling_rate):
        """Retorna (cwt_images, signals, rr_inputs) para un batch de latidos."""
        logger.info("Preparando batch de %d latidos para inferencia...", len(beats))

        rr_inputs = calculate_rr_features(r_peaks, sampling_rate)

        # Paralelizar CWT — mejora significativa en batches grandes (>100 latidos)
        with ThreadPoolExecutor(max_workers=min(_CWT_MAX_WORKERS, len(beats))) as executor:
            cwt_list = list(executor.map(apply_cwt, beats))

        cwt_images = np.expand_dims(
            np.array(cwt_list, dtype=np.float32),
            axis=-1,
        )

        signals = np.expand_dims(
            np.array(beats, dtype=np.float32),
            axis=-1,
        )

        return cwt_images, signals, rr_inputs

    @staticmethod
    def predict_chunked(beats, r_peaks, sampling_rate, ml_service, chunk_size=64):
        """
        Inferencia en chunks de `chunk_size` latidos (~4MB CWT cada uno) para evitar OOM.
        Retorna (preds, probs, rr_all).
        """
        n = len(beats)
        logger.info("Prediciendo %d latidos en chunks de %d...", n, chunk_size)

        # RR features son baratas (~32KB para 2000 latidos) — calcular todo de golpe
        rr_all = calculate_rr_features(r_peaks, sampling_rate)

        all_probs = []

        for start in range(0, n, chunk_size):
            end = min(start + chunk_size, n)
            chunk_beats = beats[start:end]
            chunk_rr = rr_all[start:end]

            with ThreadPoolExecutor(max_workers=min(_CWT_MAX_WORKERS, len(chunk_beats))) as executor:
                cwt_list = list(executor.map(apply_cwt, chunk_beats))

            cwt_imgs = np.expand_dims(
                np.array(cwt_list, dtype=np.float32), axis=-1
            )
            sigs = np.expand_dims(
                np.array(chunk_beats, dtype=np.float32), axis=-1
            )

            chunk_probs = ml_service.predict(cwt_imgs, sigs, chunk_rr)
            all_probs.append(chunk_probs)

            del cwt_imgs, sigs, cwt_list
            gc.collect()

            logger.info("Chunk %d-%d / %d completado.", start + 1, end, n)

        probs = np.concatenate(all_probs, axis=0)
        preds = np.argmax(probs, axis=1)
        return preds, probs, rr_all

    # ------------------------------------------------------------------
    # Procesamiento de archivos MIT-BIH
    # ------------------------------------------------------------------

    @staticmethod
    def process_record_with_annotations(ruta_base):
        """Carga registro MIT-BIH anotado (.atr). Raises ECGProcessingError si falla la lectura."""
        from core.exceptions import ECGProcessingError
        try:
            return procesar_archivo_mitbih(ruta_base)
        except ValueError as e:
            raise ECGProcessingError(detail=str(e))
        except Exception:
            logger.exception("Error procesando registro MIT-BIH: %s", ruta_base)
            raise ECGProcessingError(
                detail="Error inesperado al procesar el registro ECG"
            )

    @staticmethod
    def process_record_production(ruta_base):
        """Carga registro sin anotaciones con detección automática de R-peaks. Raises ECGProcessingError."""
        from core.exceptions import ECGProcessingError
        try:
            return procesar_archivo_mitbih_produccion(ruta_base)
        except ValueError as e:
            raise ECGProcessingError(detail=str(e))
        except Exception:
            logger.exception(
                "Error procesando registro producción: %s", ruta_base
            )
            raise ECGProcessingError(
                detail="Error inesperado al procesar el registro ECG"
            )

    # ------------------------------------------------------------------
    # Post-procesamiento de resultados
    # ------------------------------------------------------------------

    @staticmethod
    def build_analysis_results(preds, probs, rr_inputs, datos, max_beats=None):
        """Construye estadísticas, latidos y accuracy (si hay ground-truth) a partir de predicciones."""
        from classifier.constants import PREMATURE_BEAT_THRESHOLD

        estadisticas = {clase: 0 for clase in LABELS_MAP.values()}
        latidos = []
        has_ground_truth = 'beat_classes' in datos
        correctos = 0

        for i, pred in enumerate(preds):
            clase_pred = LABELS_MAP[pred]
            estadisticas[clase_pred] += 1

            if has_ground_truth and pred == datos['beat_classes'][i]:
                correctos += 1

            if max_beats is None or i < max_beats:
                beat_info = {
                    'indice': i,
                    'r_peak': int(datos['r_peaks'][i]),
                    'clase_predicha': clase_pred,
                    'confianza': round(float(probs[i][pred]), 4),
                    'es_prematuro': bool(
                        rr_inputs[i][2] < PREMATURE_BEAT_THRESHOLD
                    ),
                }

                if has_ground_truth:
                    beat_info['simbolo_original'] = datos['beat_symbols'][i]
                    beat_info['clase_real'] = LABELS_MAP[datos['beat_classes'][i]]
                    beat_info['es_correcto'] = bool(pred == datos['beat_classes'][i])

                latidos.append(beat_info)

        total_preds = len(preds)
        result = {
            'estadisticas': {
                'conteo': estadisticas,
                'porcentaje': {
                    k: round(v / total_preds * 100, 2) if total_preds > 0 else 0.0
                    for k, v in estadisticas.items()
                },
            },
            'latidos': latidos,
            'total_predicciones': total_preds,
        }

        if has_ground_truth:
            result['accuracy'] = round(
                (correctos / total_preds * 100) if total_preds > 0 else 0, 2
            )

        return result
