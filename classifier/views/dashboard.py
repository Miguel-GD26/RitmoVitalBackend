"""
classifier.views.dashboard — Estadísticas del dashboard.
"""

import logging

from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated

from core.responses import ApiResponse
from classifier.models import AnalisisECG
from classifier.serializers import AnalisisECGSerializer

logger = logging.getLogger(__name__)


@extend_schema(
    tags=['dashboard'],
    summary='Estadísticas agregadas del usuario autenticado',
    responses={200: OpenApiResponse(description='Métricas del dashboard')},
)
class DashboardStatsView(APIView):
    parser_classes = [JSONParser]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.core.cache import cache
        from django.db.models import Count, Avg, Sum

        user = request.user
        cache_key = f'dashboard_v1_{user.pk}'
        cached = cache.get(cache_key)
        if cached is not None:
            return ApiResponse.success(data=cached, message="Estadísticas del dashboard obtenidas")

        user_groups = set(user.groups.values_list('name', flat=True))
        if user.is_superuser or 'administrador' in user_groups:
            qs = AnalisisECG.objects.all()
        elif user_groups & {'medico', 'investigador'}:
            qs = AnalisisECG.objects.filter(usuario=user)
        elif 'paciente' in user_groups:
            qs = AnalisisECG.objects.filter(paciente__usuario_cuenta=user)
        else:
            qs = AnalisisECG.objects.none()

        qs = qs.select_related('paciente', 'usuario')
        total_analisis = qs.count()
        stats_by_mode = qs.values('modo').annotate(count=Count('id'))
        avg_accuracy = qs.filter(accuracy__isnull=False).aggregate(avg=Avg('accuracy'))['avg']
        total_latidos = qs.aggregate(total=Sum('latidos_procesados'))['total'] or 0
        recientes = list(qs.order_by('-fecha')[:5])

        data = {
            'total_analisis': total_analisis,
            'total_latidos_procesados': total_latidos,
            'accuracy_promedio': round(avg_accuracy, 2) if avg_accuracy else None,
            'por_modo': {item['modo']: item['count'] for item in stats_by_mode},
            'recientes': AnalisisECGSerializer(recientes, many=True).data,
        }
        cache.set(cache_key, data, timeout=300)
        return ApiResponse.success(data=data, message="Estadísticas del dashboard obtenidas")
