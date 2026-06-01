"""
classifier.views.infra — Endpoints de infraestructura y metadatos del modelo.
"""

import os
import logging

from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from django.conf import settings

from core.responses import ApiResponse
from classifier.services.ml_service import MLService
from classifier.constants import (
    LABELS_MAP, IMG_SIZE, LEN_SIGNAL, LEN_RR,
    MODEL_RELATIVE_PATH, PACEMAKER_RECORDS,
)

logger = logging.getLogger(__name__)


@extend_schema(
    tags=['info'],
    summary='Metadatos del modelo ML (versión, arquitectura, clases)',
    responses={200: OpenApiResponse(description='Información del modelo tri-modal ECG')},
)
class ModelInfoView(APIView):
    """Público — consumido por el frontend y útil para debugging."""
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]

    def get(self, request):
        model_path = os.path.join(settings.BASE_DIR, MODEL_RELATIVE_PATH)
        model_size_mb = None
        if os.path.exists(model_path):
            model_size_mb = round(os.path.getsize(model_path) / (1024 * 1024), 2)

        ml_service = MLService()

        return ApiResponse.success(
            data={
                'model_file': os.path.basename(MODEL_RELATIVE_PATH),
                'model_loaded': ml_service.is_ready,
                'model_size_mb': model_size_mb,
                'architecture': 'Tri-Modal CNN + MultiHeadAttention',
                'standard': 'AAMI EC57:2012',
                'dataset': 'MIT-BIH Arrhythmia Database',
                'classes': LABELS_MAP,
                'input_shapes': {
                    'cwt_image': f'(N, {IMG_SIZE}, {IMG_SIZE}, 1)',
                    'signal_1d': f'(N, {LEN_SIGNAL}, 1)',
                    'rr_intervals': f'(N, {LEN_RR})',
                },
                'pacemaker_records': list(PACEMAKER_RECORDS),
            },
            message="Información del modelo ML",
        )


@extend_schema(
    tags=['info'],
    summary='Investigadores registrados en el sistema',
    responses={200: OpenApiResponse(description='Lista de usuarios con rol investigador')},
)
class InvestigatorsView(APIView):
    """Público — lista de investigadores para mostrar en la página del modelo."""
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]

    def get(self, request):
        from django.contrib.auth.models import User
        users = (
            User.objects
            .filter(groups__name='investigador', is_active=True)
            .select_related('profile')
            .order_by('first_name', 'last_name')
        )
        data = []
        for user in users:
            profile = getattr(user, 'profile', None)
            full_name = f"{user.first_name} {user.last_name}".strip() or user.username
            data.append({
                'username':   user.username,
                'full_name':  full_name,
                'avatar_url': profile.avatar_url if profile else None,
                'orcid':      profile.orcid      if profile else '',
                'institucion': profile.institucion if profile else '',
            })
        return ApiResponse.success(data=data, message="Investigadores")


@extend_schema(
    tags=['info'],
    summary='Health check — estado del servicio y modelo ML',
    responses={
        200: OpenApiResponse(description='Servicio saludable'),
        503: OpenApiResponse(description='Servicio degradado'),
    },
)
class HealthCheckView(APIView):
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            ml_service = MLService()
            status = 'healthy' if ml_service.is_ready else 'degraded'
            return ApiResponse.success(
                data={
                    'status': status,
                    'service': 'ritmovital-backend',
                    'ml_model_loaded': ml_service.is_ready,
                },
                message="Health check completed",
            )
        except Exception as e:
            logger.error("Error en health check: %s", e)
            return ApiResponse.error(
                message="Service degraded",
                errors={"detail": str(e)},
                error_code="degraded_state",
                status_code=503,
            )
