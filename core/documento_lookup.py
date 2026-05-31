"""
core.documento_lookup — Consulta de datos por número de documento.

Orden de búsqueda:
  1. Sistema propio (UserProfile / Paciente) → fuente = 'sistema'
  2. API Graph Perú (RENIEC/SUNAT gratuita)  → fuente = 'reniec'
  3. No encontrado                            → fuente = None
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _split_nombre(full_name: str) -> tuple[str, str]:
    """
    Divide el nombre completo (formato RENIEC: APELLIDOS NOMBRES) en
    apellido y nombre.  Para DNI peruano el orden estándar es:
    APELLIDO_PAT APELLIDO_MAT NOMBRE(S).
    """
    parts = full_name.strip().split()
    if len(parts) >= 3:
        return ' '.join(parts[:2]), ' '.join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1]
    return '', full_name


def _query_graphperu(numero: str) -> dict | None:
    url = f"{getattr(settings, 'GRAPHPERU_URL', 'https://graphperu.daustinn.com/api/query')}/{numero}"
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            full_name = (data.get('fullName') or data.get('name') or '').strip()
            if full_name:
                apellido, nombre = _split_nombre(full_name)
                return {
                    'nombre':          nombre,
                    'apellido':        apellido,
                    'nombre_completo': full_name,
                    'fuente':          'reniec',
                }
    except Exception:
        logger.warning("Graph Perú no respondió para documento %s", numero)
    return None


def lookup_documento(numero: str) -> dict:
    """Busca por número de documento. fuente=None si no se encuentra nada."""
    numero = (numero or '').strip()
    if not numero:
        return {'nombre': '', 'apellido': '', 'nombre_completo': '', 'fuente': None}

    # 1. Buscar en UserProfile
    from core.models import UserProfile
    profile = UserProfile.objects.select_related('user').filter(numero_documento=numero).first()
    if profile:
        u = profile.user
        nombre   = u.first_name or ''
        apellido = u.last_name or ''
        return {
            'nombre':          nombre,
            'apellido':        apellido,
            'nombre_completo': f"{apellido} {nombre}".strip(),
            'fuente':          'sistema_usuario',
        }

    # 2. Buscar en Paciente
    from classifier.models import Paciente
    paciente = Paciente.objects.filter(numero_documento=numero).first()
    if paciente:
        return {
            'nombre':          paciente.nombre,
            'apellido':        paciente.apellido,
            'nombre_completo': f"{paciente.apellido} {paciente.nombre}".strip(),
            'fuente':          'sistema_paciente',
        }

    # 3. Consultar Graph Perú
    result = _query_graphperu(numero)
    if result:
        return result

    return {'nombre': '', 'apellido': '', 'nombre_completo': '', 'fuente': None}
