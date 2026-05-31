"""
core.permissions — Permisos RBAC para RitmoVital.

Roles disponibles (gestionados via Django Admin o setup_groups):
  - medico       : acceso completo a análisis de pacientes
  - investigador : acceso a demo/classify-random

Jerarquía: superuser > medico > investigador > authenticated
"""

from rest_framework.permissions import BasePermission


class IsMedico(BasePermission):
    """Permite acceso solo a usuarios del grupo 'medico' o superusers."""

    message = "Se requiere rol de Médico para acceder a este endpoint."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.groups.filter(name='medico').exists()


class IsPaciente(BasePermission):
    """Permite acceso solo a usuarios del grupo 'paciente'."""

    message = "Se requiere rol de Paciente para acceder a este endpoint."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.groups.filter(name='paciente').exists()


class IsInvestigador(BasePermission):
    """Permite acceso a usuarios del grupo 'investigador', 'medico', o superusers."""

    message = "Se requiere rol de Investigador o superior para acceder a este endpoint."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.groups.filter(name__in=['medico', 'investigador']).exists()
