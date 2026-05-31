"""
classifier.tasks.analysis_tasks — Tareas Celery para análisis ECG asíncrono.

Los archivos ECG se transfieren entre contenedores vía Cloudinary:
  - La vista HTTP los sube a Cloudinary y pasa las URLs al task.
  - El task los descarga de Cloudinary a un session_dir local temporal.
"""
import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache

from classifier.services.analysis_orchestrator import (
    AnalysisOrchestratorService,
    PacemakerRecordError,
    NoBeatsFoundError,
)
from classifier.services.file_service import FileService

logger = logging.getLogger(__name__)
User = get_user_model()

_CACHE_TIMEOUT = 3600  # 1 hora


def _fail(task_id: str, message: str) -> None:
    cache.set(f'analysis_task:{task_id}', {'status': 'failed', 'message': message}, timeout=_CACHE_TIMEOUT)


@shared_task(bind=True, name='classifier.tasks.analyze_annotated')
def analyze_annotated_task(self, ecg_source, record_name, paciente_id, page, page_size, user_id):
    """Análisis ECG anotado. ecg_source puede ser dict (URLs Cloudinary) o str (ruta local dev)."""
    task_id = self.request.id
    if isinstance(ecg_source, dict):
        _, session_dir = FileService.create_session()
        try:
            FileService.download_ecg_from_cloudinary(ecg_source, session_dir)
        except Exception:
            FileService.cleanup_session(session_dir)
            logger.exception("Error descargando ECG desde Cloudinary en tarea %s", task_id)
            _fail(task_id, 'Error al descargar archivos ECG desde almacenamiento.')
            return
    else:
        session_dir = ecg_source
    try:
        user = User.objects.get(pk=user_id)
        result = AnalysisOrchestratorService().run_annotated_from_session(
            session_dir=session_dir,
            record_name=record_name,
            paciente_id=paciente_id,
            page=page,
            page_size=page_size,
            user=user,
        )
        pagination = result.pop('pagination')
        cache.set(f'analysis_task:{task_id}', {
            'status': 'completed',
            'message': 'Análisis completado exitosamente',
            'result': result,
            'pagination': pagination,
        }, timeout=_CACHE_TIMEOUT)
        logger.info("Tarea anotada %s completada: %s", task_id, record_name)
    except PacemakerRecordError as e:
        _fail(task_id, f'Registro de marcapasos incompatible: {e}')
        FileService.cleanup_session(session_dir)
    except NoBeatsFoundError as e:
        _fail(task_id, str(e))
        FileService.cleanup_session(session_dir)
    except Exception:
        logger.exception("Error inesperado en tarea %s", task_id)
        _fail(task_id, 'Error interno del servidor durante el análisis.')
        FileService.cleanup_session(session_dir)
        raise


@shared_task(bind=True, name='classifier.tasks.analyze_production')
def analyze_production_task(self, ecg_source, record_name, paciente_id, page, page_size, user_id):
    """Análisis ECG producción. ecg_source puede ser dict (URLs Cloudinary) o str (ruta local dev)."""
    task_id = self.request.id
    if isinstance(ecg_source, dict):
        _, session_dir = FileService.create_session()
        try:
            FileService.download_ecg_from_cloudinary(ecg_source, session_dir)
        except Exception:
            FileService.cleanup_session(session_dir)
            logger.exception("Error descargando ECG desde Cloudinary en tarea %s", task_id)
            _fail(task_id, 'Error al descargar archivos ECG desde almacenamiento.')
            return
    else:
        session_dir = ecg_source
    try:
        user = User.objects.get(pk=user_id)
        result = AnalysisOrchestratorService().run_production_from_session(
            session_dir=session_dir,
            record_name=record_name,
            paciente_id=paciente_id,
            page=page,
            page_size=page_size,
            user=user,
        )
        pagination = result.pop('pagination')
        cache.set(f'analysis_task:{task_id}', {
            'status': 'completed',
            'message': 'Análisis completado exitosamente',
            'result': result,
            'pagination': pagination,
        }, timeout=_CACHE_TIMEOUT)
        logger.info("Tarea producción %s completada: %s", task_id, record_name)
    except PacemakerRecordError as e:
        _fail(task_id, f'Registro de marcapasos incompatible: {e}')
        FileService.cleanup_session(session_dir)
    except NoBeatsFoundError as e:
        _fail(task_id, str(e))
        FileService.cleanup_session(session_dir)
    except Exception:
        logger.exception("Error inesperado en tarea producción %s", task_id)
        _fail(task_id, 'Error interno del servidor durante el análisis.')
        FileService.cleanup_session(session_dir)
        raise
