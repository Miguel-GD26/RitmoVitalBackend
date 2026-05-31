"""
classifier.views.analysis — Vistas de análisis ECG y demo ML.
"""

import logging
import uuid

import numpy as np
from django.core.cache import cache
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser

from core.permissions import IsInvestigador
from core.responses import ApiResponse
from core.exceptions import FileValidationError
from classifier.serializers import (
    BeatIndexInputSerializer,
    AnalyzePatientSerializer,
    AnalyzePatientProductionSerializer,
    PaginationInputSerializer,
)
from classifier.services.ml_service import MLService
from classifier.services.ecg_processor import ECGProcessor
from classifier.services.visualization_service import VisualizationService
from classifier.services.file_service import FileService
from classifier.services.analysis_orchestrator import (
    AnalysisOrchestratorService,
    PacemakerRecordError,
    NoBeatsFoundError,
)
from classifier.constants import LABELS_MAP, PREMATURE_BEAT_THRESHOLD, PACEMAKER_RECORDS
from classifier.tasks.analysis_tasks import analyze_annotated_task, analyze_production_task


class AnalysisRateThrottle(UserRateThrottle):
    """Throttle específico para endpoints de análisis ECG (operaciones costosas)."""
    scope = 'analysis'


logger = logging.getLogger(__name__)


@extend_schema_view(
    get=extend_schema(
        tags=['classification'],
        summary='Obtener latido aleatorio del dataset de prueba',
        request=None,
        responses={200: OpenApiResponse(description='Latido aleatorio con gráfico ECG base64')},
    ),
    post=extend_schema(
        tags=['classification'],
        summary='Clasificar latido específico por índice',
        request=BeatIndexInputSerializer,
        responses={
            200: OpenApiResponse(description='Predicción AAMI con probabilidades y features RR'),
            400: OpenApiResponse(description='beat_index inválido o fuera de rango'),
        },
    ),
)
class ClassifyRandomView(APIView):
    """Modo demostración sobre el dataset de prueba MIT-BIH."""

    def get(self, request):
        ml_service = MLService()
        ml_service.initialize()

        if not ml_service.has_test_data:
            return ApiResponse.ml_unavailable(
                message="Dataset de prueba no disponible",
                detail="El archivo CSV de demostración no fue encontrado.",
            )

        beat_index, ecg_signal = ml_service.get_random_beat()
        ecg_plot = VisualizationService.plot_ecg_to_base64(
            ecg_signal, title='Latido Aleatorio Test Set'
        )

        return ApiResponse.success(
            data={'ecg_plot': ecg_plot, 'beat_index': beat_index},
            message="Latido aleatorio obtenido exitosamente",
        )

    def post(self, request):
        from django.core.cache import cache

        serializer = BeatIndexInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        beat_index = serializer.validated_data['beat_index']

        cache_key = f'beat_classify:{beat_index}'
        cached = cache.get(cache_key)
        if cached:
            return ApiResponse.success(data=cached, message="Clasificación completada exitosamente")

        ml_service = MLService()
        ml_service.initialize()

        if not ml_service.has_test_data:
            return ApiResponse.ml_unavailable(message="Dataset de prueba no disponible")

        if beat_index >= ml_service.test_data_size:
            return ApiResponse.validation_error(
                errors={'beat_index': [f"Índice fuera de rango. Máximo: {ml_service.test_data_size - 1}"]},
                message="Índice de latido inválido",
            )

        ecg_signal, rr_features, true_label_index = ml_service.get_beat_data(beat_index)
        ecg_processor = ECGProcessor()
        cwt_img, sig_input, rr_input = ecg_processor.prepare_single_beat(ecg_signal, rr_features)

        probabilities = ml_service.predict(cwt_img, sig_input, rr_input)[0]
        pred_index = int(np.argmax(probabilities))
        confidence = float(probabilities[pred_index])

        result_data = {
            'prediction': LABELS_MAP.get(pred_index, "Desconocido"),
            'confidence': round(confidence * 100, 2),
            'confidence_percent': int(confidence * 100),
            'true_label': LABELS_MAP.get(true_label_index, "Desconocido"),
            'is_correct': bool(pred_index == true_label_index),
            'all_probabilities': {
                LABELS_MAP[i]: round(float(p * 100), 2)
                for i, p in enumerate(probabilities)
            },
            'rr_info': {
                'pre_ratio': round(float(rr_features[2]), 4),
                'es_prematuro': bool(rr_features[2] < PREMATURE_BEAT_THRESHOLD),
            },
        }
        cache.set(cache_key, result_data, timeout=600)
        return ApiResponse.success(data=result_data, message="Clasificación completada exitosamente")


@extend_schema(
    tags=['ecg-analysis'],
    summary='Análisis ECG con anotaciones MIT-BIH (.dat + .atr + .hea)',
    request=AnalyzePatientSerializer,
    responses={200: OpenApiResponse(description='Análisis completado con accuracy vs ground-truth')},
)
class AnalyzePatientView(APIView):
    """
    Análisis de paciente con archivos MIT-BIH anotados (.dat, .atr, .hea).
    Requiere rol Médico.
    """
    parser_classes = [MultiPartParser]
    permission_classes = [IsInvestigador]
    throttle_classes = [AnalysisRateThrottle]

    def post(self, request):
        serializer = AnalyzePatientSerializer(data=request.FILES)
        serializer.is_valid(raise_exception=True)

        paciente_id = self._parse_patient_id(request)
        page, page_size = self._parse_pagination(request)

        # Guardar archivos antes de encolar (Celery no puede serializar InMemoryUploadedFile)
        try:
            _, session_dir = FileService.create_session()
            record_name = FileService.save_ecg_files_annotated(request.FILES, session_dir)
        except FileValidationError as e:
            return ApiResponse.validation_error(errors={'ecg': [str(e)]}, message='Error en archivos ECG')

        if record_name in PACEMAKER_RECORDS:
            FileService.cleanup_session(session_dir)
            return self._pacemaker_error(record_name)

        cloudinary_urls = FileService.upload_ecg_to_cloudinary(session_dir)
        FileService.cleanup_session(session_dir)

        task_id = uuid.uuid4().hex
        cache.set(f'analysis_task:{task_id}', {'status': 'pending', 'message': 'Análisis en cola...'}, timeout=3600)
        analyze_annotated_task.apply_async(
            args=[cloudinary_urls, record_name, paciente_id, page, page_size, request.user.pk],
            task_id=task_id,
        )
        return ApiResponse.success(
            data={'task_id': task_id, 'status': 'pending'},
            message='Análisis enviado al procesador',
        )

    @staticmethod
    def _parse_patient_id(request):
        raw = request.data.get('paciente_id')
        if raw:
            try:
                return int(raw)
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _parse_pagination(request):
        ser = PaginationInputSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        return ser.validated_data['page'], ser.validated_data['page_size']

    @staticmethod
    def _pacemaker_error(record_name):
        return ApiResponse.validation_error(
            errors={'ecg': [
                f'El registro "{record_name}" contiene latidos de marcapasos '
                '(MIT-BIH: 102, 104, 107, 217). '
                'El clasificador no está optimizado para este tipo de registro.'
            ]},
            message='Registro incompatible — contiene latidos de marcapasos artificial',
        )


@extend_schema(
    tags=['ecg-analysis'],
    summary='Análisis ECG producción sin anotaciones (.dat + .hea)',
    request=AnalyzePatientProductionSerializer,
    responses={200: OpenApiResponse(description='Análisis completado con detección automática de R-peaks')},
)
class AnalyzePatientProductionView(APIView):
    """
    Análisis de paciente en modo producción (.dat + .hea, sin anotaciones).
    Requiere rol Médico.
    """
    parser_classes = [MultiPartParser]
    permission_classes = [IsInvestigador]
    throttle_classes = [AnalysisRateThrottle]

    def post(self, request):
        serializer = AnalyzePatientProductionSerializer(data=request.FILES)
        serializer.is_valid(raise_exception=True)

        paciente_id = AnalyzePatientView._parse_patient_id(request)
        page, page_size = AnalyzePatientView._parse_pagination(request)

        try:
            _, session_dir = FileService.create_session()
            record_name = FileService.save_ecg_files_production(
                request.FILES['dat_file'], request.FILES['hea_file'], session_dir
            )
        except FileValidationError as e:
            return ApiResponse.validation_error(errors={'ecg': [str(e)]}, message='Error en archivos ECG')

        if record_name in PACEMAKER_RECORDS:
            FileService.cleanup_session(session_dir)
            return AnalyzePatientView._pacemaker_error(record_name)

        cloudinary_urls = FileService.upload_ecg_to_cloudinary(session_dir)
        FileService.cleanup_session(session_dir)

        task_id = uuid.uuid4().hex
        cache.set(f'analysis_task:{task_id}', {'status': 'pending', 'message': 'Análisis en cola...'}, timeout=3600)
        analyze_production_task.apply_async(
            args=[cloudinary_urls, record_name, paciente_id, page, page_size, request.user.pk],
            task_id=task_id,
        )
        return ApiResponse.success(
            data={'task_id': task_id, 'status': 'pending'},
            message='Análisis enviado al procesador',
        )


@extend_schema(
    tags=['ecg-analysis'],
    summary='Consultar estado de tarea de análisis ECG',
    responses={200: OpenApiResponse(description='Estado de la tarea (completed/pending/not_found)')},
)
class AnalysisStatusView(APIView):
    """Polling endpoint para consultar el estado de un análisis ECG asíncrono."""
    permission_classes = [IsInvestigador]

    def get(self, request, task_id: str):
        entry = cache.get(f'analysis_task:{task_id}')
        if entry is None:
            return ApiResponse.not_found(message=f'Tarea {task_id} no encontrada o expirada')

        status = entry.get('status', 'pending')
        if status == 'completed':
            result = dict(entry.get('result', {}))
            result['task_id'] = task_id
            return ApiResponse.success(
                data={'task_id': task_id, 'status': 'completed', 'result': result},
                message=entry.get('message', 'Análisis completado'),
                pagination=entry.get('pagination'),
            )
        return ApiResponse.success(
            data={'task_id': task_id, 'status': status, 'message': entry.get('message', '')},
            message=entry.get('message', ''),
        )
