"""
core.audit_middleware — Registro automático de accesos a endpoints médicos.

Guarda un AuditLog por cada request exitoso a /api/ (excluye health y auth).
"""

import logging

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset({
    '/api/health/',
    '/api/model-info/',
    '/api/auth/login/',
    '/api/auth/refresh/',
    '/api/auth/logout/',
})


class AuditLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            request.path.startswith('/api/')
            and request.path not in _SKIP_PATHS
            and response.status_code < 500
        ):
            self._log(request)

        return response

    def _log(self, request):
        try:
            from core.models import AuditLog
            ip = (
                request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
                or request.META.get('REMOTE_ADDR')
            )
            AuditLog.objects.create(
                usuario=request.user if request.user.is_authenticated else None,
                accion=request.method,
                endpoint=request.path,
                ip_address=ip or None,
            )
        except Exception:
            logger.exception("Error al registrar AuditLog")
