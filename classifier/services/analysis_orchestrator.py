"""
classifier.services.analysis_orchestrator — Lógica de negocio de análisis ECG (SRP).
"""
import logging
import os
import threading

from classifier.constants import MODEL_RELATIVE_PATH, PACEMAKER_RECORDS
from classifier.models import AnalisisECG, Paciente
from classifier.services.ecg_processor import ECGProcessor
from classifier.services.file_service import FileService
from classifier.services.ml_service import MLService, MLServicePool
from classifier.services.visualization_service import VisualizationService
from core.pagination import paginate_list

logger = logging.getLogger(__name__)

# Singleton del backend ML a nivel de proceso.
# Garantiza que MLServicePool se instancie una sola vez por worker (no por tarea),
# evitando cargar N × pool_size modelos de 450 MB en memoria simultáneamente.
_ml_backend = None
_ml_backend_lock = threading.Lock()


def _get_ml_backend():
    global _ml_backend
    if _ml_backend is not None:
        return _ml_backend
    with _ml_backend_lock:
        if _ml_backend is not None:
            return _ml_backend
        from django.conf import settings
        pool_size = getattr(settings, 'ML_POOL_SIZE', 1)
        if pool_size > 1:
            _ml_backend = MLServicePool(pool_size)
        else:
            svc = MLService()
            svc.initialize()
            _ml_backend = svc
    return _ml_backend


class PacemakerRecordError(Exception):
    """El registro contiene latidos de marcapasos incompatibles con el clasificador."""


class NoBeatsFoundError(Exception):
    """No se encontraron latidos válidos en el registro."""


class AnalysisOrchestratorService:

    def __init__(self):
        self._ml = _get_ml_backend()
        self._processor = ECGProcessor()

    # ------------------------------------------------------------------
    # API pública — gestión de sesión + delegación al núcleo
    # ------------------------------------------------------------------

    def run_annotated(self, files, paciente_id, page, page_size, user):
        """Análisis en modo anotado (.dat + .atr + .hea). Raises PacemakerRecordError / NoBeatsFoundError."""
        session_id, session_dir = FileService.create_session()
        try:
            record_name = FileService.save_ecg_files_annotated(files, session_dir)
            return self._run_annotated_core(session_dir, record_name, paciente_id, page, page_size, user)
        finally:
            FileService.cleanup_session(session_dir)

    def run_annotated_from_session(self, session_dir, record_name, paciente_id, page, page_size, user):
        """run_annotated sobre sesión preexistente — usado por Celery (evita pasar bytes al worker)."""
        try:
            return self._run_annotated_core(session_dir, record_name, paciente_id, page, page_size, user)
        finally:
            FileService.cleanup_session(session_dir)

    def run_production(self, files, paciente_id, page, page_size, user):
        """Análisis en modo producción (.dat + .hea, sin anotaciones). Raises PacemakerRecordError / NoBeatsFoundError."""
        session_id, session_dir = FileService.create_session()
        try:
            record_name = FileService.save_ecg_files_production(
                files['dat_file'], files['hea_file'], session_dir
            )
            return self._run_production_core(session_dir, record_name, paciente_id, page, page_size, user)
        finally:
            FileService.cleanup_session(session_dir)

    def run_production_from_session(self, session_dir, record_name, paciente_id, page, page_size, user):
        """run_production sobre sesión preexistente — usado por Celery."""
        try:
            return self._run_production_core(session_dir, record_name, paciente_id, page, page_size, user)
        finally:
            FileService.cleanup_session(session_dir)

    # ------------------------------------------------------------------
    # Núcleos privados — lógica de análisis sin gestión de sesión
    # ------------------------------------------------------------------

    def _run_annotated_core(self, session_dir, record_name, paciente_id, page, page_size, user):
        self._check_pacemaker(record_name)
        ruta_base = FileService.get_record_path(session_dir, record_name)
        logger.info("Procesando registro anotado %s...", record_name)

        datos = self._processor.process_record_with_annotations(ruta_base)
        if not datos['beats']:
            raise NoBeatsFoundError("No se encontraron latidos válidos en el registro")

        preds, probs, rr_inputs = self._processor.predict_chunked(
            datos['beats'], datos['r_peaks'], datos['sampling_rate'], self._ml
        )
        analysis = self._processor.build_analysis_results(preds, probs, rr_inputs, datos)
        paginated_beats, pagination_meta = paginate_list(
            analysis['latidos'], page=page, page_size=page_size
        )
        plot_url, signal_plot = self._generate_plot(
            datos['signal'], datos['sampling_rate'], title=f'Registro {record_name}'
        )
        self._save_analisis(
            user=user, record_name=record_name, modo='anotado',
            total=datos['total_beats_detected'],
            procesados=analysis['total_predicciones'],
            accuracy=analysis.get('accuracy'),
            paciente_id=paciente_id, plot_url=plot_url,
            distribucion=analysis['estadisticas']['porcentaje'],
            modelo_version=self._ml.version or os.path.basename(MODEL_RELATIVE_PATH),
        )
        return {
            'record_name': record_name,
            'total_latidos': datos['total_beats_detected'],
            'latidos_procesados': analysis['total_predicciones'],
            'latidos_excluidos': datos['beats_excluded'],
            'simbolos_excluidos': datos['excluded_symbols'],
            'sampling_rate': datos['sampling_rate'],
            'accuracy': analysis.get('accuracy'),
            'estadisticas': analysis['estadisticas'],
            'signal_plot': signal_plot,
            'latidos': paginated_beats,
            'pagination': pagination_meta,
        }

    def _run_production_core(self, session_dir, record_name, paciente_id, page, page_size, user):
        self._check_pacemaker(record_name)
        ruta_base = FileService.get_record_path(session_dir, record_name)
        logger.info("Procesando registro producción %s...", record_name)

        datos = self._processor.process_record_production(ruta_base)
        if not datos['beats']:
            raise NoBeatsFoundError("No se detectaron latidos en el registro")

        preds, probs, rr_inputs = self._processor.predict_chunked(
            datos['beats'], datos['r_peaks'], datos['sampling_rate'], self._ml
        )
        analysis = self._processor.build_analysis_results(preds, probs, rr_inputs, datos)
        paginated_beats, pagination_meta = paginate_list(
            analysis['latidos'], page=page, page_size=page_size
        )
        plot_url, signal_plot = self._generate_plot(
            datos['signal'], datos['sampling_rate'], title=f'Análisis {record_name}'
        )
        self._save_analisis(
            user=user, record_name=record_name, modo='produccion',
            total=datos['total_beats_detected'],
            procesados=len(datos['beats']),
            accuracy=None,
            paciente_id=paciente_id, plot_url=plot_url,
            distribucion=analysis['estadisticas']['porcentaje'],
            modelo_version=self._ml.version or os.path.basename(MODEL_RELATIVE_PATH),
        )
        return {
            'record_name': record_name,
            'total_latidos': datos['total_beats_detected'],
            'sampling_rate': datos['sampling_rate'],
            'estadisticas': analysis['estadisticas'],
            'signal_plot': signal_plot,
            'latidos': paginated_beats,
            'pagination': pagination_meta,
        }

    # ------------------------------------------------------------------
    # Helpers estáticos
    # ------------------------------------------------------------------

    @staticmethod
    def _check_pacemaker(record_name: str) -> None:
        if record_name in PACEMAKER_RECORDS:
            raise PacemakerRecordError(record_name)

    @staticmethod
    def _generate_plot(signal, sampling_rate, title: str):
        """Genera gráfico ECG; devuelve (plot_url, signal_plot)."""
        segment = signal[:sampling_rate * 5]
        plot_url = VisualizationService.plot_ecg_to_cloudinary(
            segment, title=title, sampling_rate=sampling_rate
        )
        signal_plot = plot_url or VisualizationService.plot_ecg_to_base64(
            segment, title=title, sampling_rate=sampling_rate
        )
        return plot_url, signal_plot

    @staticmethod
    def _save_analisis(user, record_name, modo, total, procesados,
                       accuracy, paciente_id, plot_url, distribucion, modelo_version):
        paciente = None
        if paciente_id:
            try:
                paciente = Paciente.objects.get(pk=paciente_id)
            except Paciente.DoesNotExist:
                logger.warning("paciente_id=%s no encontrado al guardar análisis", paciente_id)

        AnalisisECG.objects.create(
            usuario=user if getattr(user, 'is_authenticated', False) else None,
            paciente=paciente,
            record_name=record_name,
            modo=modo,
            total_latidos=total,
            latidos_procesados=procesados,
            accuracy=accuracy,
            modelo_version=modelo_version,
            ecg_plot_url=plot_url,
            distribucion_json=distribucion,
        )
