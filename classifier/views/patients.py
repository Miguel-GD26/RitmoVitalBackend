"""
classifier.views.patients — CRUD de pacientes.
"""

import logging

from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework.views import APIView

from core.permissions import IsInvestigador
from rest_framework.permissions import IsAdminUser
from core.responses import ApiResponse
from core.pagination import build_pagination_metadata
from classifier.models import Paciente
from classifier.serializers import (
    PacienteSerializer,
    PacienteWriteSerializer,
    PaginationInputSerializer,
)

logger = logging.getLogger(__name__)


def _resolve_usuario_cuenta(numero_documento: str):
    """Busca un UserProfile con ese DNI y retorna su User si no tiene paciente vinculado."""
    if not numero_documento:
        return None
    from core.models import UserProfile
    try:
        profile = UserProfile.objects.select_related('user').get(numero_documento=numero_documento)
        if not hasattr(profile.user, 'paciente_perfil'):
            return profile.user
    except UserProfile.DoesNotExist:
        pass
    return None


@extend_schema(
    tags=['patients'],
    summary='Listar o crear pacientes del médico autenticado',
    responses={200: OpenApiResponse(description='Lista paginada de pacientes')},
)
class PatientListView(APIView):
    permission_classes = [IsInvestigador | IsAdminUser]

    def get(self, request):
        from django.db.models import Q

        pagination_ser = PaginationInputSerializer(data=request.query_params)
        pagination_ser.is_valid(raise_exception=True)
        page = pagination_ser.validated_data['page']
        page_size = pagination_ser.validated_data['page_size']

        search = request.query_params.get('search', '').strip()
        sexo   = request.query_params.get('sexo', '').strip().upper()
        # Admin e investigador ven todos; médico solo los suyos
        see_all = request.user.is_staff or request.user.groups.filter(name='investigador').exists()
        qs = Paciente.objects.all() if see_all else Paciente.objects.filter(creado_por=request.user)
        if search:
            qs = qs.filter(
                Q(nombre__icontains=search) |
                Q(apellido__icontains=search) |
                Q(historia_clinica__icontains=search)
            )
        if sexo in ('M', 'F', 'O'):
            qs = qs.filter(sexo=sexo)

        total = qs.count()
        start = (page - 1) * page_size
        page_items = list(qs[start:start + page_size])

        return ApiResponse.success(
            data=PacienteSerializer(page_items, many=True).data,
            pagination=build_pagination_metadata(total, page, page_size),
            message="Lista de pacientes obtenida",
        )

    def post(self, request):
        ser = PacienteWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        numero = ser.validated_data.get('numero_documento', '').strip()
        paciente = ser.save(
            creado_por=request.user,
            usuario_cuenta=_resolve_usuario_cuenta(numero),
        )
        return ApiResponse.created(
            data=PacienteSerializer(paciente).data,
            message="Paciente registrado exitosamente",
        )


@extend_schema(
    tags=['patients'],
    summary='Obtener, actualizar o eliminar un paciente',
    responses={200: OpenApiResponse(description='Detalle del paciente')},
)
class PatientDetailView(APIView):
    permission_classes = [IsInvestigador | IsAdminUser]

    def _get_object(self, request, uuid):
        try:
            see_all = request.user.is_staff or request.user.groups.filter(name='investigador').exists()
            if see_all:
                return Paciente.objects.get(uuid=uuid)
            return Paciente.objects.get(uuid=uuid, creado_por=request.user)
        except Paciente.DoesNotExist:
            return None

    def get(self, request, uuid):
        paciente = self._get_object(request, uuid)
        if not paciente:
            return ApiResponse.not_found("Paciente no encontrado")
        return ApiResponse.success(data=PacienteSerializer(paciente).data)

    def put(self, request, uuid):
        paciente = self._get_object(request, uuid)
        if not paciente:
            return ApiResponse.not_found("Paciente no encontrado")
        ser = PacienteWriteSerializer(paciente, data=request.data)
        ser.is_valid(raise_exception=True)
        nuevo_dni = ser.validated_data.get('numero_documento', '').strip()
        dni_cambio = nuevo_dni != (paciente.numero_documento or '')
        save_kwargs = {}
        if dni_cambio:
            save_kwargs['usuario_cuenta'] = _resolve_usuario_cuenta(nuevo_dni)
        return ApiResponse.success(
            data=PacienteSerializer(ser.save(**save_kwargs)).data,
            message="Paciente actualizado",
        )

    def patch(self, request, uuid):
        paciente = self._get_object(request, uuid)
        if not paciente:
            return ApiResponse.not_found("Paciente no encontrado")
        ser = PacienteWriteSerializer(paciente, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        nuevo_dni = ser.validated_data.get('numero_documento', paciente.numero_documento or '').strip()
        dni_cambio = 'numero_documento' in ser.validated_data and nuevo_dni != (paciente.numero_documento or '')
        save_kwargs = {}
        if dni_cambio:
            save_kwargs['usuario_cuenta'] = _resolve_usuario_cuenta(nuevo_dni)
        return ApiResponse.success(
            data=PacienteSerializer(ser.save(**save_kwargs)).data,
            message="Paciente actualizado",
        )

    def delete(self, request, uuid):
        paciente = self._get_object(request, uuid)
        if not paciente:
            return ApiResponse.not_found("Paciente no encontrado")
        paciente.delete()
        return ApiResponse.success(message="Paciente eliminado")


@extend_schema(tags=['patients'], summary='Vincular o desvincular cuenta de usuario a un paciente (solo admin)')
class PatientVincularView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, uuid):
        """Vincular: crea cuenta y la enlaza al paciente, o enlaza una cuenta existente por email."""
        try:
            paciente = Paciente.objects.get(uuid=uuid)
        except Paciente.DoesNotExist:
            return ApiResponse.not_found("Paciente no encontrado")

        if paciente.usuario_cuenta:
            return ApiResponse.error("Este paciente ya tiene una cuenta vinculada.", status_code=400)

        from django.contrib.auth.models import User, Group
        from core.models import UserProfile

        email    = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email:
            return ApiResponse.validation_error({'email': ['El correo es requerido.']})

        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            if hasattr(existing, 'paciente_perfil'):
                return ApiResponse.error("Ese usuario ya está vinculado a otro paciente.", status_code=400)
            paciente.usuario_cuenta = existing
            paciente.save()
            return ApiResponse.success(
                data=PacienteSerializer(paciente).data,
                message="Paciente vinculado a cuenta existente."
            )

        if not password or len(password) < 6:
            return ApiResponse.validation_error({'password': ['Mínimo 6 caracteres.']})

        base = email.split('@')[0]
        username, counter = base, 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'; counter += 1

        user = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=paciente.nombre, last_name=paciente.apellido,
        )
        group, _ = Group.objects.get_or_create(name='paciente')
        user.groups.add(group)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.tipo_documento   = paciente.tipo_documento
        profile.numero_documento = paciente.numero_documento
        profile.save()

        paciente.usuario_cuenta = user
        paciente.save()

        logger.info("Admin %s vinculó paciente %s con nueva cuenta %s", request.user.username, uuid, email)
        return ApiResponse.created(
            data=PacienteSerializer(paciente).data,
            message="Cuenta creada y vinculada al paciente."
        )

    def delete(self, request, uuid):
        try:
            paciente = Paciente.objects.get(uuid=uuid)
        except Paciente.DoesNotExist:
            return ApiResponse.not_found("Paciente no encontrado")

        if not paciente.usuario_cuenta:
            return ApiResponse.error("Este paciente no tiene cuenta vinculada.", status_code=400)

        paciente.usuario_cuenta = None
        paciente.save()
        return ApiResponse.success(data=PacienteSerializer(paciente).data, message="Cuenta desvinculada.")
