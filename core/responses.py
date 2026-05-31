"""
core.responses — Wrapper estandarizado de respuestas API.

Estructura éxito:  {success, message, data, [pagination], timestamp}
Estructura error:  {success, message, errors, error_code, timestamp}
"""

from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone


class ApiResponse:

    @staticmethod
    def success(data=None, message="Operación exitosa",
                status_code=status.HTTP_200_OK, pagination=None):
        response_body = {
            "success": True,
            "message": message,
            "data": data,
            "timestamp": timezone.now().isoformat(),
        }
        if pagination is not None:
            response_body["pagination"] = pagination
        return Response(response_body, status=status_code)

    @staticmethod
    def created(data=None, message="Recurso creado exitosamente"):
        return ApiResponse.success(
            data=data,
            message=message,
            status_code=status.HTTP_201_CREATED,
        )

    @staticmethod
    def error(message="Error interno del servidor", errors=None,
              error_code="INTERNAL_ERROR",
              status_code=status.HTTP_500_INTERNAL_SERVER_ERROR):
        return Response({
            "success": False,
            "message": message,
            "errors": errors or {},
            "error_code": error_code,
            "timestamp": timezone.now().isoformat(),
        }, status=status_code)

    @staticmethod
    def validation_error(errors, message="Error de validación"):
        return ApiResponse.error(
            message=message,
            errors=errors,
            error_code="VALIDATION_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    @staticmethod
    def not_found(message="Recurso no encontrado", errors=None):
        return ApiResponse.error(
            message=message,
            errors=errors,
            error_code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    @staticmethod
    def ml_unavailable(message="Modelo ML no disponible", detail=None):
        return ApiResponse.error(
            message=message,
            errors={"detail": detail or "El modelo de inferencia no está disponible"},
            error_code="ML_MODEL_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def ml_inference_error(message="Error durante la inferencia ML", detail=None):
        return ApiResponse.error(
            message=message,
            errors={"detail": detail or "El modelo no pudo procesar la señal ECG"},
            error_code="ML_INFERENCE_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @staticmethod
    def file_error(message="Error en archivo subido", errors=None):
        return ApiResponse.error(
            message=message,
            errors=errors or {},
            error_code="FILE_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
