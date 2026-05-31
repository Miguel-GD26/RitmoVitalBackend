"""
classifier.services.visualization_service — Generación y almacenamiento de gráficos ECG.

Genera gráficos ECG con matplotlib (backend Agg no-GUI) y los sube a Cloudinary.
Si Cloudinary no está configurado, retorna base64 como fallback.
"""

import base64
import logging
from io import BytesIO

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)


class VisualizationService:

    BACKGROUND_COLOR = '#ffffff'
    CARD_COLOR        = '#f1f6fc'
    TEXT_COLOR        = '#1A202C'
    GRID_COLOR        = (0.0, 0.0, 0.0, 0.08)
    LINE_COLOR        = '#174a7a'

    @classmethod
    def _build_figure(cls, signal, title: str, sampling_rate: int) -> BytesIO:
        fig, ax = plt.subplots(figsize=(8, 4))
        fig.patch.set_facecolor(cls.BACKGROUND_COLOR)
        ax.set_facecolor(cls.CARD_COLOR)

        time_ms = np.arange(len(signal)) * (1000 / sampling_rate)
        ax.plot(time_ms, signal, color=cls.LINE_COLOR, linewidth=2)

        ax.set_title(title, color=cls.TEXT_COLOR, fontsize=14, weight='bold')
        ax.set_xlabel('Tiempo (ms)', color=cls.TEXT_COLOR, fontsize=10)
        ax.set_ylabel('Amplitud (norm)', color=cls.TEXT_COLOR, fontsize=10)
        ax.tick_params(axis='x', colors=cls.TEXT_COLOR)
        ax.tick_params(axis='y', colors=cls.TEXT_COLOR)

        for spine in ax.spines.values():
            spine.set_color(cls.GRID_COLOR)
        ax.grid(True, color=cls.GRID_COLOR, linestyle='--', linewidth=0.5, alpha=0.7)

        plt.tight_layout()
        buf = BytesIO()
        plt.savefig(buf, format='png', facecolor=cls.BACKGROUND_COLOR, edgecolor='none')
        plt.close(fig)
        buf.seek(0)
        return buf

    @classmethod
    def plot_ecg_to_base64(cls, signal, title='Señal de ECG', sampling_rate=360) -> str:
        """Retorna el gráfico ECG como string base64 (usado en demo mode)."""
        buf = cls._build_figure(signal, title, sampling_rate)
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    @classmethod
    def plot_ecg_to_cloudinary(cls, signal, title='Señal de ECG',
                                sampling_rate=360, public_id: str = None) -> str | None:
        """Sube ECG a Cloudinary y retorna la URL segura, o None si Cloudinary no está configurado."""
        from django.conf import settings

        if not getattr(settings, 'CLOUDINARY_ENABLED', False):
            logger.warning("Cloudinary no configurado — plot ECG no será almacenado.")
            return None

        try:
            import cloudinary.uploader

            buf = cls._build_figure(signal, title, sampling_rate)

            upload_opts = {
                'folder': 'ritmovital/ecg_plots',
                'resource_type': 'image',
                'format': 'png',
                'overwrite': True,
            }
            if public_id:
                upload_opts['public_id'] = public_id

            result = cloudinary.uploader.upload(buf, **upload_opts)
            return result.get('secure_url')

        except Exception:
            logger.exception("Error al subir gráfico ECG a Cloudinary")
            return None
