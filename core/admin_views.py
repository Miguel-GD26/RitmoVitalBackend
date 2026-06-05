"""
core.admin_views — Gestión de usuarios y roles (solo superusuarios).
"""

import logging

import cloudinary.uploader
from django.conf import settings
from django.contrib.auth.models import User, Group
from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser

from core.models import UserProfile
from core.responses import ApiResponse
from core.pagination import build_pagination_metadata

logger = logging.getLogger(__name__)


def _serialize_user(user: User) -> dict:
    groups = list(user.groups.values_list('name', flat=True))
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile, _ = UserProfile.objects.get_or_create(user=user)
    return {
        'id': user.pk,
        'uuid': str(profile.uuid),
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_active': user.is_active,
        'is_superuser': user.is_superuser,
        'role': groups[0] if groups else None,
        'avatar_url': profile.avatar_url,
        'date_joined': user.date_joined.isoformat(),
        'tipo_documento':    profile.tipo_documento,
        'numero_documento':  profile.numero_documento,
        'fecha_nacimiento':  profile.fecha_nacimiento.isoformat() if profile.fecha_nacimiento else None,
        'sexo':              profile.sexo,
        'numero_colegiatura': profile.numero_colegiatura,
        'orcid':       profile.orcid,
        'institucion': profile.institucion,
    }


@extend_schema(tags=['admin'], summary='Listar y crear usuarios')
class AdminUserListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        search    = request.query_params.get('search', '').strip()
        role      = request.query_params.get('role', '').strip()
        page      = max(int(request.query_params.get('page', 1)), 1)
        page_size = min(int(request.query_params.get('page_size', 20)), 100)

        qs = User.objects.select_related('profile').prefetch_related('groups').order_by('-date_joined')

        if search:
            qs = qs.filter(
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )
        if role:
            qs = qs.filter(groups__name=role)

        total = qs.count()
        start = (page - 1) * page_size
        users = list(qs[start:start + page_size])

        return ApiResponse.success(
            data=[_serialize_user(u) for u in users],
            pagination=build_pagination_metadata(total, page, page_size),
            message="Lista de usuarios obtenida",
        )

    def post(self, request):
        email      = request.data.get('email', '').strip().lower()
        first_name = request.data.get('first_name', '').strip()
        last_name  = request.data.get('last_name', '').strip()
        password   = request.data.get('password', '')
        role       = request.data.get('role', 'medico')

        errors = {}
        if not email:
            errors['email'] = ['El correo es requerido.']
        elif User.objects.filter(email__iexact=email).exists():
            errors['email'] = ['Ya existe una cuenta con este correo.']
        if not password or len(password) < 6:
            errors['password'] = ['La contraseña debe tener al menos 6 caracteres.']
        if role not in ('medico', 'paciente', 'investigador', 'administrador'):
            errors['role'] = ['Rol inválido.']
        if errors:
            return ApiResponse.validation_error(errors=errors)

        base = email.split('@')[0]
        username, counter = base, 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'; counter += 1

        user = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=first_name, last_name=last_name,
            is_staff=(role == 'administrador'),
        )
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.tipo_documento    = request.data.get('tipo_documento', 'DNI')
        profile.numero_documento  = request.data.get('numero_documento', '').strip()
        profile.fecha_nacimiento  = request.data.get('fecha_nacimiento') or None
        profile.sexo              = request.data.get('sexo', '').strip()
        profile.numero_colegiatura = request.data.get('numero_colegiatura', '').strip()
        profile.orcid       = request.data.get('orcid', '').strip()
        profile.institucion = request.data.get('institucion', '').strip()
        profile.save()

        # Auto-link si existe un Paciente con el mismo número de documento
        numero = profile.numero_documento
        if numero:
            from classifier.models import Paciente
            Paciente.objects.filter(
                numero_documento=numero, usuario_cuenta__isnull=True
            ).update(usuario_cuenta=user)

        logger.info("Admin %s creó usuario %s con rol %s", request.user.username, email, role)
        return ApiResponse.created(data=_serialize_user(user), message=f'Usuario creado con rol {role}.')


@extend_schema(tags=['admin'], summary='Editar o desactivar un usuario')
class AdminUserDetailView(APIView):
    """
    SRP: put() solo orquesta. Cada responsabilidad vive en su propio método:
      _update_basic_data  → datos personales y estado de la cuenta
      _assign_role        → membresía de grupos y flag is_staff
      _update_profile     → campos extendidos del perfil
    """
    permission_classes = [IsAdminUser]

    def _get(self, uuid):
        try:
            profile = UserProfile.objects.select_related('user').prefetch_related('user__groups').get(uuid=uuid)
            return profile.user
        except UserProfile.DoesNotExist:
            return None

    def put(self, request, uuid):
        user = self._get(uuid)
        if not user:
            return ApiResponse.not_found("Usuario no encontrado")
        if user.is_superuser:
            return ApiResponse.error("No se puede editar a un superusuario.", status_code=403)

        self._update_basic_data(user, request.data)
        self._assign_role(user, request.data.get('role'))
        self._update_profile(user, request.data)

        return ApiResponse.success(data=_serialize_user(user), message="Usuario actualizado")

    def delete(self, request, uuid):
        user = self._get(uuid)
        if not user:
            return ApiResponse.not_found("Usuario no encontrado")
        if user.pk == request.user.pk:
            return ApiResponse.error("No puedes desactivar tu propia cuenta.", status_code=400)
        if user.is_superuser:
            return ApiResponse.error("No se puede desactivar a un superusuario.", status_code=403)

        user.is_active = False
        user.save(update_fields=['is_active'])
        return ApiResponse.success(message="Usuario desactivado correctamente")

    @staticmethod
    def _update_basic_data(user, data) -> None:
        user.first_name = data.get('first_name', user.first_name)
        user.last_name  = data.get('last_name',  user.last_name)
        user.is_active  = data.get('is_active',  user.is_active)
        user.save(update_fields=['first_name', 'last_name', 'is_active'])

    @staticmethod
    def _assign_role(user, role) -> None:
        if role is None:
            return
        user.groups.clear()
        if role:
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
        user.is_staff = (role == 'administrador')
        user.save(update_fields=['is_staff'])

    @staticmethod
    def _update_profile(user, data) -> None:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        fields_map = {
            'tipo_documento':    lambda v: v,
            'numero_documento':  lambda v: v.strip(),
            'fecha_nacimiento':  lambda v: v or None,
            'sexo':              lambda v: v.strip(),
            'numero_colegiatura': lambda v: v.strip(),
            'orcid':             lambda v: v.strip(),
            'institucion':       lambda v: v.strip(),
        }
        updated = []
        for field, transform in fields_map.items():
            if field in data:
                setattr(profile, field, transform(data[field]))
                updated.append(field)
        if updated:
            profile.save(update_fields=updated)


@extend_schema(tags=['admin'], summary='Subir o actualizar avatar de usuario')
class AdminUserAvatarView(APIView):
    permission_classes = [IsAdminUser]

    def put(self, request, uuid):
        try:
            profile = UserProfile.objects.select_related('user').get(uuid=uuid)
        except UserProfile.DoesNotExist:
            return ApiResponse.not_found("Usuario no encontrado")

        avatar_file = request.FILES.get('avatar')
        if not avatar_file:
            return ApiResponse.validation_error({'avatar': ['Se requiere un archivo de imagen.']})

        allowed = ('image/jpeg', 'image/png', 'image/gif', 'image/webp')
        if avatar_file.content_type not in allowed:
            return ApiResponse.validation_error({'avatar': ['Formato no válido. Usa JPG, PNG, GIF o WebP.']})

        if avatar_file.size > 2 * 1024 * 1024:
            return ApiResponse.validation_error({'avatar': ['El archivo no puede superar 2 MB.']})

        if not getattr(settings, 'CLOUDINARY_ENABLED', False):
            return ApiResponse.error("Cloudinary no está configurado.", status_code=503)

        try:
            result = cloudinary.uploader.upload(
                avatar_file,
                folder='ritmovital/avatars',
                public_id=f'user_{profile.user_id}',
                overwrite=True,
                transformation=[{'width': 256, 'height': 256, 'crop': 'fill', 'gravity': 'face'}],
            )
            avatar_url = result.get('secure_url')
        except Exception:
            logger.exception("Error al subir avatar de usuario %s a Cloudinary", uuid)
            return ApiResponse.error("Error al subir la imagen.")

        profile.avatar_url = avatar_url
        profile.save()

        return ApiResponse.success(data={'avatar_url': avatar_url}, message="Avatar actualizado")


@extend_schema(tags=['admin'], summary='Listar roles con permisos y conteo de usuarios')
class AdminRoleListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        groups = (
            Group.objects
            .prefetch_related('permissions')
            .annotate(user_count=Count('user'))
            .order_by('name')
        )
        data = [
            {
                'id': g.id,
                'name': g.name,
                'user_count': g.user_count,
                'permissions': [
                    {'id': p.id, 'codename': p.codename, 'name': p.name}
                    for p in g.permissions.all()
                ],
            }
            for g in groups
        ]
        return ApiResponse.success(data=data, message="Roles obtenidos")


_MODEL_LABELS: dict[str, str] = {
    'analisisecg':  'Análisis ECG',
    'paciente':     'Pacientes',
    'userprofile':  'Perfiles de usuario',
    'auditlog':     'Registro de auditoría',
    'user':         'Usuarios del sistema',
    'group':        'Grupos y roles',
    'permission':   'Permisos',
}

# Apps que se exponen en la UI (se excluyen las de Django internals)
_ALLOWED_APPS = {'classifier', 'auth'}


@extend_schema(tags=['admin'], summary='Listar todos los permisos disponibles agrupados por modelo')
class AdminPermissionListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from django.contrib.auth.models import Permission

        perms = (
            Permission.objects
            .select_related('content_type')
            .filter(content_type__app_label__in=_ALLOWED_APPS)
            .order_by('content_type__app_label', 'content_type__model', 'codename')
        )

        groups: dict[str, dict] = {}
        for p in perms:
            ct  = p.content_type
            key = f'{ct.app_label}.{ct.model}'
            if key not in groups:
                groups[key] = {
                    'key':   key,
                    'label': _MODEL_LABELS.get(ct.model, ct.model.replace('_', ' ').title()),
                    'permissions': [],
                }
            groups[key]['permissions'].append({
                'id':       p.id,
                'codename': p.codename,
                'name':     p.name,
            })

        return ApiResponse.success(data=list(groups.values()), message="Permisos obtenidos")


@extend_schema(tags=['admin'], summary='Actualizar permisos de un rol')
class AdminRoleUpdateView(APIView):
    permission_classes = [IsAdminUser]

    def put(self, request, pk):
        from django.contrib.auth.models import Permission

        try:
            group = Group.objects.prefetch_related('permissions').get(pk=pk)
        except Group.DoesNotExist:
            return ApiResponse.not_found("Rol no encontrado")

        permission_ids = request.data.get('permission_ids', [])
        if not isinstance(permission_ids, list):
            return ApiResponse.validation_error({'permission_ids': ['Debe ser una lista de IDs.']})

        perms = Permission.objects.filter(id__in=permission_ids)
        group.permissions.set(perms)

        data = {
            'id':           group.id,
            'name':         group.name,
            'user_count':   group.user_set.count(),
            'permissions':  [
                {'id': p.id, 'codename': p.codename, 'name': p.name}
                for p in group.permissions.all()
            ],
        }
        logger.info("Admin %s actualizó permisos del rol '%s'", request.user.username, group.name)
        return ApiResponse.success(data=data, message=f'Permisos del rol "{group.name}" actualizados.')
