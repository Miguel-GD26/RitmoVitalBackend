"""
classifier.services.ml_service — Singleton thread-safe del modelo Keras.

NUNCA se debe importar TensorFlow ni ejecutar model.predict() fuera de este módulo.
"""

import hashlib
import os
import queue
import random
import threading
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from django.conf import settings

from classifier.constants import (
    LEN_SIGNAL, LEN_RR, IMG_SIZE, LABELS_MAP,
    MODEL_RELATIVE_PATH, TEST_DATA_RELATIVE_PATH,
)

logger = logging.getLogger(__name__)


class MLService:
    """Singleton thread-safe del modelo de inferencia ECG. Carga modelo + warmup con double-check locking."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._model = None
                    instance._test_data = None
                    instance._initialized = False
                    instance._inference_lock = threading.Lock()
                    instance._model_sha256 = None
                    instance._model_version = None
                    cls._instance = instance
        return cls._instance

    # ------------------------------------------------------------------
    # Inicialización
    # ------------------------------------------------------------------

    def initialize(self):
        """Carga modelo + warmup. Idempotente."""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._load_model()
            self._warmup()
            self._initialized = True

    @staticmethod
    def _download_if_missing(abs_path, url_env_var):
        """Downloads file from env-var URL if it doesn't exist locally."""
        if os.path.exists(abs_path):
            return
        url = os.environ.get(url_env_var, '').strip()
        if not url:
            raise FileNotFoundError(
                f"Archivo no encontrado: {abs_path}. "
                f"Define la variable de entorno {url_env_var} con la URL de descarga."
            )
        import requests  # lazy — avoid slowing down module init
        logger.info("Descargando %s desde %s ...", os.path.basename(abs_path), url)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        # Descarga atómica: escribe a .tmp y renombra al final.
        # Si el proceso muere a mitad, el .tmp queda incompleto y el archivo
        # final no existe, forzando un reintento en el próximo arranque.
        tmp_path = abs_path + '.tmp'
        try:
            with requests.get(url, stream=True, timeout=300) as r:
                r.raise_for_status()
                total = int(r.headers.get('Content-Length', 0))
                downloaded = 0
                with open(tmp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
            os.replace(tmp_path, abs_path)  # atómico en Linux
            mb = downloaded / 1024 / 1024
            expected_mb = total / 1024 / 1024 if total else '?'
            logger.info("Descarga completada: %.1f / %s MB → %s", mb, expected_mb, abs_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    @staticmethod
    def _compute_sha256(path: str) -> str:
        """SHA256 del archivo en bloques de 1 MB."""
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    def _load_model(self):
        model_path = os.path.join(settings.BASE_DIR, MODEL_RELATIVE_PATH)
        self._download_if_missing(model_path, 'MODEL_URL')
        logger.info("Cargando modelo tri-modal desde %s ...", model_path)

        self._model_version = os.path.basename(model_path)
        self._model_sha256 = self._compute_sha256(model_path)
        logger.info("Modelo: %s | SHA256: %s", self._model_version, self._model_sha256)

        # Forzar CPU — apropiado para servidor web
        os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

        from tensorflow.keras.layers import MultiHeadAttention, LayerNormalization
        custom_objects = {
            "MultiHeadAttention": MultiHeadAttention,
            "LayerNormalization": LayerNormalization,
        }

        try:
            self._model = tf.keras.models.load_model(
                model_path, custom_objects=custom_objects
            )
            logger.info("Modelo cargado exitosamente.")
        except Exception:
            logger.exception("Error crítico al cargar modelo ML.")
            self._model = None
            raise

    def _warmup(self):
        logger.info("Ejecutando warmup del modelo...")
        dummy_img = np.zeros((1, IMG_SIZE, IMG_SIZE, 1), dtype=np.float32)
        dummy_sig = np.zeros((1, LEN_SIGNAL, 1), dtype=np.float32)
        dummy_rr = np.zeros((1, LEN_RR), dtype=np.float32)
        self._model.predict(
            {'cwt_image': dummy_img, 'signal_1d': dummy_sig, 'rr_intervals': dummy_rr},
            verbose=0,
        )
        logger.info("Warmup completado — modelo listo para inferencia.")

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def is_ready(self):
        return self._initialized and self._model is not None

    @property
    def model_version(self) -> str | None:
        return self._model_version

    @property
    def model_sha256(self) -> str | None:
        return self._model_sha256

    @property
    def version(self) -> str | None:
        """Versión compacta: stem@sha256[:8] (útil para auditoría)."""
        if self._model_sha256 is None:
            return None
        return f"{Path(MODEL_RELATIVE_PATH).stem}@{self._model_sha256[:8]}"

    # ------------------------------------------------------------------
    # Test data (modo demo) — carga lazy
    # ------------------------------------------------------------------

    def _ensure_test_data(self):
        if self._test_data is not None:
            return
        test_path = os.path.join(settings.BASE_DIR, TEST_DATA_RELATIVE_PATH)
        try:
            self._download_if_missing(test_path, 'TEST_DATA_URL')
        except FileNotFoundError:
            logger.warning("Dataset de prueba no disponible (sin TEST_DATA_URL): %s", test_path)
            self._test_data = None
            return
        except Exception as exc:
            logger.warning("Error descargando dataset de prueba: %s", exc)
            self._test_data = None
            return
        logger.info("Cargando dataset de prueba desde %s ...", test_path)
        self._test_data = pd.read_csv(test_path, header=None, dtype=np.float32)
        logger.info("Dataset cargado: %d registros.", len(self._test_data))

    @property
    def has_test_data(self):
        self._ensure_test_data()
        return self._test_data is not None

    @property
    def test_data_size(self):
        self._ensure_test_data()
        return len(self._test_data) if self._test_data is not None else 0

    def get_random_beat(self):
        """Retorna (beat_index, ecg_signal) aleatorio del dataset de prueba."""
        self._ensure_test_data()
        if self._test_data is None:
            raise ValueError("Dataset de prueba no disponible")

        idx = random.randint(0, len(self._test_data) - 1)
        signal = self._test_data.iloc[idx, :LEN_SIGNAL].values.astype(np.float32)
        return idx, signal

    def get_beat_data(self, beat_index):
        """Retorna (ecg_signal, rr_features, true_label_index) para el latido dado. Raises IndexError si fuera de rango."""
        self._ensure_test_data()
        if self._test_data is None:
            raise ValueError("Dataset de prueba no disponible")
        if beat_index < 0 or beat_index >= len(self._test_data):
            raise IndexError(
                f"beat_index {beat_index} fuera de rango [0, {len(self._test_data) - 1}]"
            )

        row = self._test_data.iloc[beat_index]
        ecg_signal = row[:LEN_SIGNAL].values.astype(np.float32)
        rr_features = row[LEN_SIGNAL:LEN_SIGNAL + LEN_RR].values.astype(np.float32)
        true_label = int(row.iloc[-1])
        return ecg_signal, rr_features, true_label

    # ------------------------------------------------------------------
    # Predicción
    # ------------------------------------------------------------------

    def predict(self, cwt_images, signals, rr_features, batch_size=32):
        """Inferencia tri-modal. Retorna probabilidades (N, num_classes). Raises MLModelNotAvailableError si no listo."""
        if not self.is_ready:
            from core.exceptions import MLModelNotAvailableError
            raise MLModelNotAvailableError()

        # Validar shapes antes de enviar a TensorFlow
        n = cwt_images.shape[0]
        if cwt_images.shape != (n, IMG_SIZE, IMG_SIZE, 1):
            raise ValueError(
                f"cwt_images shape {cwt_images.shape} — esperado ({n}, {IMG_SIZE}, {IMG_SIZE}, 1)"
            )
        if signals.shape != (n, LEN_SIGNAL, 1):
            raise ValueError(
                f"signals shape {signals.shape} — esperado ({n}, {LEN_SIGNAL}, 1)"
            )
        if rr_features.shape != (n, LEN_RR):
            raise ValueError(
                f"rr_features shape {rr_features.shape} — esperado ({n}, {LEN_RR})"
            )

        t0 = time.monotonic()
        with self._inference_lock:
            result = self._model.predict(
                {
                    'cwt_image': cwt_images,
                    'signal_1d': signals,
                    'rr_intervals': rr_features,
                },
                batch_size=batch_size,
                verbose=0,
            )
        latency_s = time.monotonic() - t0
        logger.info(
            'ml_inference_completed',
            extra={
                'latency_s': round(latency_s, 3),
                'batch_size': n,
                'latency_per_beat_ms': round(latency_s / n * 1000, 2) if n > 0 else 0,
            },
        )
        if latency_s > 60:
            logger.warning(
                'ml_inference_slow',
                extra={'latency_s': round(latency_s, 3), 'batch_size': n},
            )
        return result

    def predict_single(self, cwt_image, signal, rr_features):
        """Inferencia de un latido. Retorna dict {pred_index, pred_label, confidence, all_probabilities}."""
        cwt_input = cwt_image.reshape(1, IMG_SIZE, IMG_SIZE, 1)
        sig_input = signal.reshape(1, LEN_SIGNAL, 1)
        rr_input = rr_features.reshape(1, LEN_RR)

        probabilities = self.predict(cwt_input, sig_input, rr_input)[0]
        pred_index = int(np.argmax(probabilities))
        confidence = float(probabilities[pred_index])

        return {
            'pred_index': pred_index,
            'pred_label': LABELS_MAP.get(pred_index, "Desconocido"),
            'confidence': round(confidence * 100, 2),
            'all_probabilities': {
                LABELS_MAP[i]: round(float(p * 100), 2)
                for i, p in enumerate(probabilities)
            },
        }


class MLServicePool:
    """
    Pool thread-safe de N instancias del modelo para inferencia paralela.

    Cada instancia ocupa ~450 MB. Configurar ML_POOL_SIZE en settings según RAM:
      Railway Starter (512 MB): ML_POOL_SIZE=1  → usa MLService (comportamiento actual)
      Railway Pro   (4 GB):     ML_POOL_SIZE=4  → 4 análisis simultáneos sin bloqueo

    Expone la misma interfaz que MLService (predict, version, is_ready)
    para ser intercambiable en AnalysisOrchestratorService.
    """

    def __init__(self, pool_size: int):
        self._pool: queue.Queue = queue.Queue(maxsize=pool_size)
        self._version_str: str | None = None
        self._sha256: str | None = None

        model_path = os.path.join(settings.BASE_DIR, MODEL_RELATIVE_PATH)
        MLService._download_if_missing(model_path, 'MODEL_URL')
        sha256 = MLService._compute_sha256(model_path)
        self._sha256 = sha256
        self._version_str = f"{Path(MODEL_RELATIVE_PATH).stem}@{sha256[:8]}"

        os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
        from tensorflow.keras.layers import MultiHeadAttention, LayerNormalization
        custom_objects = {
            'MultiHeadAttention': MultiHeadAttention,
            'LayerNormalization': LayerNormalization,
        }

        logger.info("Iniciando pool ML con %d instancias (%s)...", pool_size, self._version_str)
        dummy_img = np.zeros((1, IMG_SIZE, IMG_SIZE, 1), dtype=np.float32)
        dummy_sig = np.zeros((1, LEN_SIGNAL, 1), dtype=np.float32)
        dummy_rr  = np.zeros((1, LEN_RR), dtype=np.float32)

        for i in range(pool_size):
            model = tf.keras.models.load_model(model_path, custom_objects=custom_objects)
            model.predict(
                {'cwt_image': dummy_img, 'signal_1d': dummy_sig, 'rr_intervals': dummy_rr},
                verbose=0,
            )
            self._pool.put(model)
            logger.info("Instancia ML %d/%d lista.", i + 1, pool_size)

        logger.info("Pool ML listo: %d instancias disponibles.", pool_size)

    # ------------------------------------------------------------------
    # Interfaz pública (compatible con MLService)
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return not self._pool.empty() or self._version_str is not None

    @property
    def version(self) -> str | None:
        return self._version_str

    @property
    def model_sha256(self) -> str | None:
        return self._sha256

    def predict(self, cwt_images, signals, rr_features, batch_size=32):
        n = cwt_images.shape[0]
        if cwt_images.shape != (n, IMG_SIZE, IMG_SIZE, 1):
            raise ValueError(f"cwt_images shape {cwt_images.shape} — esperado ({n}, {IMG_SIZE}, {IMG_SIZE}, 1)")
        if signals.shape != (n, LEN_SIGNAL, 1):
            raise ValueError(f"signals shape {signals.shape} — esperado ({n}, {LEN_SIGNAL}, 1)")
        if rr_features.shape != (n, LEN_RR):
            raise ValueError(f"rr_features shape {rr_features.shape} — esperado ({n}, {LEN_RR})")

        model = self._pool.get(timeout=120)  # max 2 min en cola si todas las instancias ocupadas
        try:
            t0 = time.monotonic()
            result = model.predict(
                {'cwt_image': cwt_images, 'signal_1d': signals, 'rr_intervals': rr_features},
                batch_size=batch_size,
                verbose=0,
            )
            latency_s = time.monotonic() - t0
            logger.info(
                'ml_inference_completed',
                extra={
                    'latency_s': round(latency_s, 3),
                    'batch_size': n,
                    'latency_per_beat_ms': round(latency_s / n * 1000, 2) if n > 0 else 0,
                },
            )
            if latency_s > 60:
                logger.warning('ml_inference_slow', extra={'latency_s': round(latency_s, 3), 'batch_size': n})
            return result
        finally:
            self._pool.put(model)
