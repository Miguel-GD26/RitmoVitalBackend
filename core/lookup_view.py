"""
core.lookup_view — Endpoint de consulta de documento por número.
Accesible para cualquier usuario autenticado (médico, admin, etc.).
"""

from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.documento_lookup import lookup_documento
from core.responses import ApiResponse


@extend_schema(
    tags=['lookup'],
    summary='Buscar nombre por número de documento (sistema → RENIEC)',
    parameters=[
        OpenApiParameter('numero', str, OpenApiParameter.QUERY, required=True,
                         description='Número de documento (DNI 8 dígitos, CE, etc.)'),
    ],
)
class DocumentoLookupView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        numero = request.query_params.get('numero', '').strip()
        if not numero:
            return ApiResponse.validation_error({'numero': ['El número de documento es requerido.']})

        result = lookup_documento(numero)
        return ApiResponse.success(data=result, message="Consulta completada")
