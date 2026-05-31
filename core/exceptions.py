"""
core.exceptions — Excepciones de dominio y handler DRF centralizado.

El handler garantiza que NUNCA se expongan tracebacks ni rutas internas al cliente.
"""

import logging
from django.utils import timezone
from rest_framework.views import exception_handler
from rest_framework import status
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Excepciones personalizadas del dominio
# ---------------------------------------------------------------------------

class MLModelNotAvailableError(APIException):
    """El modelo ML no está cargado o no pudo inicializarse."""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "El modelo de inferencia no está disponible en este momento."
    default_code = "ML_MODEL_UNAVAILABLE"


class MLInferenceError(APIException):
    """Error durante la ejecución de model.predict()."""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = "Error durante el procesamiento de la señal ECG."
    default_code = "ML_INFERENCE_ERROR"


class ECGProcessingError(APIException):
    """Error al procesar o parsear archivos ECG (wfdb, CWT, etc.)."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "No se pudo procesar la señal ECG proporcionada."
    default_code = "ECG_PROCESSING_ERROR"


class FileValidationError(APIException):
    """Archivo subido no cumple validaciones (extensión, tamaño, nombre)."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "El archivo subido no es válido."
    default_code = "FILE_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Handler centralizado de excepciones DRF
# ---------------------------------------------------------------------------

def custom_exception_handler(exc, context):
    """Handler DRF global. Normaliza todas las respuestas de error al formato ApiResponse."""
    view = context.get("view", None)
    view_name = view.__class__.__name__ if view else "Unknown"

    response = exception_handler(exc, context)

    if response is not None:
        error_code = getattr(exc, "default_code", "DRF_ERROR")

        if isinstance(response.data, dict):
            errors = response.data
        elif isinstance(response.data, list):
            errors = {"detail": response.data}
        else:
            errors = {"detail": str(response.data)}

        if hasattr(exc, "detail"):
            if isinstance(exc.detail, str):
                message = exc.detail
            elif isinstance(exc.detail, dict):
                message = "Error de validación en los datos de entrada"
            elif isinstance(exc.detail, list):
                message = str(exc.detail[0]) if exc.detail else "Error de validación"
            else:
                message = str(exc.detail)
        else:
            message = "Error en la solicitud"

        response.data = {
            "success": False,
            "message": message,
            "errors": errors,
            "error_code": str(error_code),
            "timestamp": timezone.now().isoformat(),
        }

        logger.warning(
            "Excepción manejada en %s: [%s] %s",
            view_name, error_code, message,
        )

    else:
        # Traceback al servidor, nunca al cliente
        logger.exception(
            "Excepción no manejada en %s: %s", view_name, exc,
        )

        from rest_framework.response import Response
        response = Response(
            {
                "success": False,
                "message": "Error interno del servidor",
                "errors": {},
                "error_code": "INTERNAL_ERROR",
                "timestamp": timezone.now().isoformat(),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response
