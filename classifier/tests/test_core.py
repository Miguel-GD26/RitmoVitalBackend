"""
Tests del módulo core — ApiResponse, paginación, y exception handler.

Verifica que la infraestructura compartida funciona correctamente
y produce respuestas con el formato estandarizado.
"""

from django.test import TestCase, RequestFactory
from rest_framework import status
from rest_framework.exceptions import ValidationError, NotFound
from rest_framework.test import APIRequestFactory

from core.responses import ApiResponse
from core.pagination import build_pagination_metadata, paginate_list
from core.exceptions import (
    custom_exception_handler,
    MLModelNotAvailableError,
    MLInferenceError,
    ECGProcessingError,
    FileValidationError,
)


# ---------------------------------------------------------------------------
# ApiResponse Tests
# ---------------------------------------------------------------------------

class ApiResponseSuccessTests(TestCase):
    """Tests de ApiResponse.success()."""

    def test_success_response_format(self):
        """Respuesta exitosa tiene estructura {success, message, data, timestamp}."""
        response = ApiResponse.success(
            data={'key': 'value'},
            message='Test exitoso',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.data
        self.assertTrue(body['success'])
        self.assertEqual(body['message'], 'Test exitoso')
        self.assertEqual(body['data'], {'key': 'value'})
        self.assertIn('timestamp', body)

    def test_success_default_message(self):
        """Sin mensaje explícito, usa el default."""
        response = ApiResponse.success()
        self.assertEqual(response.data['message'], 'Operación exitosa')

    def test_success_with_none_data(self):
        """data=None es válido."""
        response = ApiResponse.success(data=None)
        self.assertIsNone(response.data['data'])

    def test_success_custom_status_code(self):
        """Puede usar status codes personalizados."""
        response = ApiResponse.success(status_code=status.HTTP_201_CREATED)
        self.assertEqual(response.status_code, 201)

    def test_success_with_pagination(self):
        """Campo pagination se incluye cuando se pasa."""
        pagination = {'total': 100, 'page': 1}
        response = ApiResponse.success(data=[], pagination=pagination)

        body = response.data
        self.assertIn('pagination', body)
        self.assertEqual(body['pagination']['total'], 100)

    def test_success_without_pagination(self):
        """Sin paginación, el campo pagination no aparece."""
        response = ApiResponse.success(data={'key': 'value'})
        self.assertNotIn('pagination', response.data)


class ApiResponseErrorTests(TestCase):
    """Tests de ApiResponse.error() y variantes."""

    def test_error_response_format(self):
        """Respuesta de error tiene estructura {success, message, errors, error_code, timestamp}."""
        response = ApiResponse.error(
            message='Test error',
            errors={'field': ['Error detalle']},
            error_code='TEST_ERROR',
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        body = response.data
        self.assertFalse(body['success'])
        self.assertEqual(body['message'], 'Test error')
        self.assertEqual(body['error_code'], 'TEST_ERROR')
        self.assertIn('timestamp', body)

    def test_validation_error(self):
        """validation_error() retorna 400."""
        response = ApiResponse.validation_error(
            errors={'beat_index': ['Campo requerido']},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')

    def test_not_found(self):
        """not_found() retorna 404."""
        response = ApiResponse.not_found()
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['error_code'], 'NOT_FOUND')

    def test_ml_unavailable(self):
        """ml_unavailable() retorna 503."""
        response = ApiResponse.ml_unavailable()
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['error_code'], 'ML_MODEL_UNAVAILABLE')

    def test_ml_inference_error(self):
        """ml_inference_error() retorna 500."""
        response = ApiResponse.ml_inference_error()
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data['error_code'], 'ML_INFERENCE_ERROR')

    def test_file_error(self):
        """file_error() retorna 400."""
        response = ApiResponse.file_error()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'FILE_ERROR')

    def test_created_response(self):
        """created() retorna 201."""
        response = ApiResponse.created(data={'id': 1})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])

    def test_error_empty_errors_default(self):
        """errors=None resulta en dict vacío."""
        response = ApiResponse.error()
        self.assertEqual(response.data['errors'], {})


# ---------------------------------------------------------------------------
# Pagination Tests
# ---------------------------------------------------------------------------

class BuildPaginationMetadataTests(TestCase):
    """Tests de build_pagination_metadata()."""

    def test_basic_pagination(self):
        """Paginación básica con 250 items, page=1, page_size=100."""
        result = build_pagination_metadata(250, page=1, page_size=100)

        self.assertEqual(result['total'], 250)
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['page_size'], 100)
        self.assertEqual(result['total_pages'], 3)
        self.assertTrue(result['has_next'])
        self.assertFalse(result['has_previous'])

    def test_last_page(self):
        """Última página tiene has_next=False."""
        result = build_pagination_metadata(250, page=3, page_size=100)

        self.assertEqual(result['page'], 3)
        self.assertFalse(result['has_next'])
        self.assertTrue(result['has_previous'])

    def test_middle_page(self):
        """Página intermedia tiene has_next=True y has_previous=True."""
        result = build_pagination_metadata(250, page=2, page_size=100)

        self.assertTrue(result['has_next'])
        self.assertTrue(result['has_previous'])

    def test_single_page(self):
        """Con pocos items, solo hay 1 página."""
        result = build_pagination_metadata(50, page=1, page_size=100)

        self.assertEqual(result['total_pages'], 1)
        self.assertFalse(result['has_next'])
        self.assertFalse(result['has_previous'])

    def test_empty_list(self):
        """Lista vacía retorna total=0, total_pages=1."""
        result = build_pagination_metadata(0, page=1, page_size=100)

        self.assertEqual(result['total'], 0)
        self.assertEqual(result['total_pages'], 1)

    def test_page_clamped_to_max(self):
        """Si page > total_pages, se clampea al máximo."""
        result = build_pagination_metadata(50, page=999, page_size=100)

        self.assertEqual(result['page'], 1)  # Solo 1 página


class PaginateListTests(TestCase):
    """Tests de paginate_list()."""

    def test_first_page(self):
        """Primera página retorna los primeros page_size items."""
        items = list(range(250))
        page_items, meta = paginate_list(items, page=1, page_size=100)

        self.assertEqual(len(page_items), 100)
        self.assertEqual(page_items[0], 0)
        self.assertEqual(page_items[-1], 99)
        self.assertEqual(meta['total'], 250)

    def test_last_page_partial(self):
        """Última página puede tener menos de page_size items."""
        items = list(range(250))
        page_items, meta = paginate_list(items, page=3, page_size=100)

        self.assertEqual(len(page_items), 50)
        self.assertEqual(page_items[0], 200)

    def test_empty_list(self):
        """Lista vacía retorna lista vacía con metadata correcta."""
        page_items, meta = paginate_list([], page=1, page_size=100)

        self.assertEqual(len(page_items), 0)
        self.assertEqual(meta['total'], 0)


# ---------------------------------------------------------------------------
# Custom Exception Handler Tests
# ---------------------------------------------------------------------------

class CustomExceptionHandlerTests(TestCase):
    """Tests del handler centralizado de excepciones."""

    def _make_context(self):
        """Crea un contexto mock para el exception handler."""
        mock_view = type('MockView', (), {'__class__': type('V', (), {'__name__': 'TestView'})})()
        return {'view': mock_view, 'request': None}

    def test_drf_validation_error_formatted(self):
        """DRF ValidationError se formatea con el envelope estándar."""
        exc = ValidationError({'beat_index': ['Este campo es requerido.']})
        context = self._make_context()

        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertFalse(response.data['success'])
        self.assertIn('error_code', response.data)
        self.assertIn('timestamp', response.data)
        self.assertIn('errors', response.data)

    def test_drf_not_found_formatted(self):
        """DRF NotFound se formatea con el envelope estándar."""
        exc = NotFound()
        context = self._make_context()

        response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data['success'])

    def test_custom_ml_exception_formatted(self):
        """MLModelNotAvailableError se formatea correctamente."""
        exc = MLModelNotAvailableError()
        context = self._make_context()

        response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'ML_MODEL_UNAVAILABLE')

    def test_unhandled_exception_returns_generic_error(self):
        """Excepciones no-DRF retornan error genérico sin detalles internos."""
        exc = RuntimeError("Internal database connection failed at /opt/secret/path")
        context = self._make_context()

        response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'INTERNAL_ERROR')
        # El mensaje genérico NO debe contener el detalle interno
        self.assertNotIn('database', response.data['message'].lower())
        self.assertNotIn('/opt/', response.data['message'])

    def test_ecg_processing_error_formatted(self):
        """ECGProcessingError se formatea como 400."""
        exc = ECGProcessingError(detail="Señal ECG corrupta")
        context = self._make_context()

        response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])

    def test_file_validation_error_formatted(self):
        """FileValidationError se formatea como 400."""
        exc = FileValidationError(detail="Extensión no permitida")
        context = self._make_context()

        response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
