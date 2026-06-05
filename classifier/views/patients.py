"""
classifier.views.patients — CRUD de pacientes.
"""

import logging

from django.contrib.auth.models import User
from django.db.models import Q
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from classifier.models import Paciente
from classifier.serializers import (
    PacienteSerializer,
    PacienteWriteSerializer,
    PaginationInputSerializer,
)
from classifier.services.patient_service import (
    UsuarioYaVinculadoError,
    crear_y_vincular_cuenta,
    vincular_cuenta_existente,
)
from core.models import UserProfile
from core.pagination import build_pagination_metadata
from core.permissions import IsInvestigador
from core.responses import ApiResponse

logger = logging.getLogger(__name__)


def _resolve_usuario_cuenta(numero_documento: str):
    """Busca un UserProfile con ese DNI y retorna su User si no tiene paciente vinculado."""
    if not numero_documento:
        return None
    try:
        profile = UserProfile.objects.select_related('user').get(numero_documento=numero_documento)
        if not Paciente.objects.filter(usuario_cuenta=profile.user).exists():
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
        pagination_ser = PaginationInputSerializer(data=request.query_params)
        pagination_ser.is_valid(raise_exception=True)
        page      = pagination_ser.validated_data['page']
        page_size = pagination_ser.validated_data['page_size']

        search = request.query_params.get('search', '').strip()
        sexo   = request.query_params.get('sexo', '').strip().upper()

        user_groups = set(request.user.groups.values_list('name', flat=True))
        see_all = request.user.is_staff or 'investigador' in user_groups

        qs = (
            Paciente.objects
            .select_related('creado_por', 'usuario_cuenta')
            .all() if see_all
            else Paciente.objects
            .select_related('creado_por', 'usuario_cuenta')
            .filter(creado_por=request.user)
        )
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

        numero   = ser.validated_data.get('numero_documento', '').strip()
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
        user_groups = set(request.user.groups.values_list('name', flat=True))
        see_all = request.user.is_staff or 'investigador' in user_groups
        qs = Paciente.objects.select_related('creado_por', 'usuario_cuenta')
        try:
            return qs.get(uuid=uuid) if see_all else qs.get(uuid=uuid, creado_por=request.user)
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
        nuevo_dni  = ser.validated_data.get('numero_documento', '').strip()
        save_kwargs = {}
        if nuevo_dni != (paciente.numero_documento or ''):
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
        save_kwargs = {}
        if 'numero_documento' in ser.validated_data:
            nuevo_dni = ser.validated_data['numero_documento'].strip()
            if nuevo_dni != (paciente.numero_documento or ''):
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
        """Vincular: enlaza cuenta existente o crea una nueva. Toda la lógica está en patient_service."""
        try:
            paciente = Paciente.objects.get(uuid=uuid)
        except Paciente.DoesNotExist:
            return ApiResponse.not_found("Paciente no encontrado")

        if paciente.usuario_cuenta:
            return ApiResponse.error("Este paciente ya tiene una cuenta vinculada.", status_code=400)

        email    = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email:
            return ApiResponse.validation_error({'email': ['El correo es requerido.']})

        # ¿Ya existe un usuario con ese email?
        if User.objects.filter(email__iexact=email).exists():
            try:
                vincular_cuenta_existente(paciente, email)
            except UsuarioYaVinculadoError:
                return ApiResponse.error("Ese usuario ya está vinculado a otro paciente.", status_code=400)
            return ApiResponse.success(
                data=PacienteSerializer(paciente).data,
                message="Paciente vinculado a cuenta existente.",
            )

        if not password:
            return ApiResponse.validation_error({'password': ['La contraseña es requerida para crear la cuenta.']})

        try:
            crear_y_vincular_cuenta(paciente, email, password)
        except ValueError as e:
            return ApiResponse.validation_error({'password': [str(e)]})

        logger.info("Admin %s vinculó paciente %s con nueva cuenta %s", request.user.username, uuid, email)
        return ApiResponse.created(
            data=PacienteSerializer(paciente).data,
            message="Cuenta creada y vinculada al paciente. Se envió un correo de verificación.",
        )

    def delete(self, request, uuid):
        try:
            paciente = Paciente.objects.get(uuid=uuid)
        except Paciente.DoesNotExist:
            return ApiResponse.not_found("Paciente no encontrado")

        if not paciente.usuario_cuenta:
            return ApiResponse.error("Este paciente no tiene cuenta vinculada.", status_code=400)

        paciente.usuario_cuenta = None
        paciente.save(update_fields=['usuario_cuenta'])
        return ApiResponse.success(data=PacienteSerializer(paciente).data, message="Cuenta desvinculada.")
