"""
classifier.views.history — Historial, PDF y CSV de análisis ECG.
"""

import csv
import io
import logging

from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated

from core.responses import ApiResponse
from core.pagination import build_pagination_metadata
from core.permissions import IsMedico, IsPaciente
from classifier.models import AnalisisECG
from classifier.serializers import AnalisisECGSerializer, PaginationInputSerializer
from classifier.services.pdf_service import generate_analysis_pdf

logger = logging.getLogger(__name__)


@extend_schema(
    tags=['history'],
    summary='Historial paginado de análisis ECG del usuario autenticado',
    responses={200: OpenApiResponse(description='Lista paginada de análisis ECG')},
)
class AnalysisHistoryView(APIView):
    parser_classes = [JSONParser]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pagination_ser = PaginationInputSerializer(data=request.query_params)
        pagination_ser.is_valid(raise_exception=True)
        page      = pagination_ser.validated_data['page']
        page_size = pagination_ser.validated_data['page_size']

        qs = AnalisisECG.objects.select_related('paciente', 'usuario').order_by('-fecha')

        user = request.user
        if user.is_superuser or user.groups.filter(name='administrador').exists():
            pass  # ve todos los análisis
        elif user.groups.filter(name__in=['medico', 'investigador']).exists():
            qs = qs.filter(usuario=user)
        elif user.groups.filter(name='paciente').exists():
            qs = qs.filter(paciente__usuario_cuenta=user)
        else:
            qs = qs.none()

        modo        = request.query_params.get('modo', '').strip()
        search      = request.query_params.get('search', '').strip()
        paciente_id = request.query_params.get('paciente_id', '').strip()

        if modo:
            qs = qs.filter(modo=modo)
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(record_name__icontains=search) |
                Q(paciente__nombre__icontains=search) |
                Q(paciente__apellido__icontains=search)
            )
        if paciente_id:
            qs = qs.filter(paciente_id=paciente_id)

        total = qs.count()
        start = (page - 1) * page_size
        page_items = list(qs[start:start + page_size])

        return ApiResponse.success(
            data=AnalisisECGSerializer(page_items, many=True).data,
            pagination=build_pagination_metadata(total, page, page_size),
            message="Historial de análisis obtenido",
        )


@extend_schema(
    tags=['history'],
    summary='Descargar reporte PDF de un análisis ECG',
    responses={200: OpenApiResponse(description='Archivo PDF descargable')},
)
class AnalysisPdfView(APIView):
    parser_classes = [JSONParser]
    permission_classes = [IsAuthenticated]

    def get(self, request, uuid):
        try:
            analisis = AnalisisECG.objects.select_related('paciente', 'usuario').get(
                uuid=uuid, usuario=request.user
            )
        except AnalisisECG.DoesNotExist:
            return ApiResponse.not_found("Análisis no encontrado")

        return generate_analysis_pdf(analisis)


@extend_schema(
    tags=['history'],
    summary='Exportar historial de análisis ECG como CSV',
    responses={200: OpenApiResponse(description='Archivo CSV descargable')},
)
class AnalysisCsvExportView(APIView):
    """Incluye BOM UTF-8 para compatibilidad con Excel."""
    parser_classes = [JSONParser]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import HttpResponse
        from django.utils import timezone

        qs = (
            AnalisisECG.objects
            .filter(usuario=request.user)
            .select_related('paciente')
            .order_by('-fecha')
        )

        output = io.StringIO()
        output.write('﻿')  # BOM UTF-8 — compatibilidad Excel
        writer = csv.writer(output)

        writer.writerow([
            'ID', 'Registro ECG', 'Modo', 'Paciente', 'Historia Clínica',
            'Total Latidos', 'Latidos Procesados', 'Accuracy (%)',
            'Versión Modelo', 'Fecha (UTC)',
        ])

        for a in qs:
            paciente_nombre = (
                f"{a.paciente.nombre} {a.paciente.apellido}" if a.paciente else ''
            )
            writer.writerow([
                a.id,
                a.record_name or '',
                a.get_modo_display(),
                paciente_nombre,
                a.paciente.historia_clinica if a.paciente else '',
                a.total_latidos,
                a.latidos_procesados,
                f'{a.accuracy:.4f}' if a.accuracy is not None else '',
                a.modelo_version,
                a.fecha.strftime('%Y-%m-%d %H:%M:%S'),
            ])

        ts = timezone.now().strftime('%Y%m%d_%H%M')
        fname = f'historial_ecg_{request.user.username}_{ts}.csv'
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{fname}"'
        return response
