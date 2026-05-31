"""
Management command: python manage.py setup_groups

Crea los grupos RBAC de RitmoVital con sus permisos de modelo.

Grupos:
  medico       — CRUD completo sobre Paciente + crear/ver AnalisisECG
  paciente     — solo ver sus propios AnalisisECG y su registro Paciente
  investigador — acceso solo a endpoints demo (classify-random)
"""

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand


GROUPS = {
    'medico': {
        'description': 'Acceso completo: CRUD pacientes + análisis ECG',
        'permissions': [
            ('classifier', 'paciente',    'add_paciente'),
            ('classifier', 'paciente',    'change_paciente'),
            ('classifier', 'paciente',    'delete_paciente'),
            ('classifier', 'paciente',    'view_paciente'),
            ('classifier', 'analisisecg', 'add_analisisecg'),
            ('classifier', 'analisisecg', 'view_analisisecg'),
        ],
    },
    'paciente': {
        'description': 'Solo lectura: ver su propio historial ECG',
        'permissions': [
            ('classifier', 'analisisecg', 'view_analisisecg'),
            ('classifier', 'paciente',    'view_paciente'),
        ],
    },
    'investigador': {
        'description': 'Acceso demo: classify-random únicamente',
        'permissions': [],
    },
}


class Command(BaseCommand):
    help = 'Crea los grupos RBAC de RitmoVital con sus permisos'

    def handle(self, *args, **options):
        for group_name, config in GROUPS.items():
            group, created = Group.objects.get_or_create(name=group_name)
            status = 'creado' if created else 'actualizado'

            perms_to_assign = []
            for app_label, model_name, codename in config['permissions']:
                try:
                    ct = ContentType.objects.get(app_label=app_label, model=model_name)
                    perm = Permission.objects.get(content_type=ct, codename=codename)
                    perms_to_assign.append(perm)
                except (ContentType.DoesNotExist, Permission.DoesNotExist) as e:
                    self.stdout.write(self.style.WARNING(f'  Permiso no encontrado: {codename} ({e})'))

            group.permissions.set(perms_to_assign)
            self.stdout.write(self.style.SUCCESS(
                f'Grupo "{group_name}" — {status} con {len(perms_to_assign)} permiso(s).'
            ))

        self.stdout.write(self.style.SUCCESS(
            '\nPara asignar un rol:\n'
            '  python manage.py shell\n'
            '  >>> from django.contrib.auth.models import User, Group\n'
            '  >>> u = User.objects.get(username="juan")\n'
            '  >>> u.groups.add(Group.objects.get(name="medico"))  # o "paciente"\n'
        ))
