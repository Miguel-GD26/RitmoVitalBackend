"""
classifier.tests.test_patient_service — Tests unitarios de la capa de servicio de pacientes.

Cubre:
  - vincular_cuenta_existente: happy path, user no encontrado, user ya vinculado
  - crear_y_vincular_cuenta: creación completa, validación de password, grupo, perfil
  - _unique_username: sin conflicto, conflicto simple, múltiples conflictos
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from classifier.models import Paciente
from classifier.services.patient_service import (
    UsuarioYaVinculadoError,
    _unique_username,
    crear_y_vincular_cuenta,
    vincular_cuenta_existente,
)
from core.models import UserProfile


def _make_creator(tag='a'):
    return User.objects.create_user(
        username=f'creator_{tag}', password='x', email=f'creator_{tag}@test.com'
    )


def _make_paciente(creator, hc='HC001', **kwargs):
    defaults = dict(nombre='Ana', apellido='García', historia_clinica=hc, creado_por=creator)
    defaults.update(kwargs)
    return Paciente.objects.create(**defaults)


# ---------------------------------------------------------------------------
# vincular_cuenta_existente
# ---------------------------------------------------------------------------

class TestVincularCuentaExistente(TestCase):

    def setUp(self):
        self.creator = _make_creator('vc')
        self.paciente = _make_paciente(self.creator, 'HC010')
        self.target = User.objects.create_user(
            username='pedro', email='pedro@test.com', password='Pass123!'
        )

    def test_vincula_paciente_a_usuario_existente(self):
        vincular_cuenta_existente(self.paciente, 'pedro@test.com')
        self.paciente.refresh_from_db()
        self.assertEqual(self.paciente.usuario_cuenta, self.target)

    def test_raises_does_not_exist_si_email_no_existe(self):
        with self.assertRaises(User.DoesNotExist):
            vincular_cuenta_existente(self.paciente, 'noexiste@test.com')

    def test_raises_usuario_ya_vinculado_si_user_tiene_otro_paciente(self):
        _make_paciente(self.creator, 'HC011', usuario_cuenta=self.target)
        with self.assertRaises(UsuarioYaVinculadoError):
            vincular_cuenta_existente(self.paciente, 'pedro@test.com')

    def test_paciente_sin_vinculo_previo_no_lanza(self):
        try:
            vincular_cuenta_existente(self.paciente, 'pedro@test.com')
        except Exception as e:
            self.fail(f'No esperaba excepción: {e}')

    def test_vincula_sin_modificar_otros_campos(self):
        vincular_cuenta_existente(self.paciente, 'pedro@test.com')
        self.paciente.refresh_from_db()
        self.assertEqual(self.paciente.nombre, 'Ana')
        self.assertEqual(self.paciente.historia_clinica, 'HC010')

    def test_lookup_de_email_es_case_insensitive(self):
        vincular_cuenta_existente(self.paciente, 'PEDRO@TEST.COM')
        self.paciente.refresh_from_db()
        self.assertEqual(self.paciente.usuario_cuenta, self.target)


# ---------------------------------------------------------------------------
# crear_y_vincular_cuenta
# ---------------------------------------------------------------------------

class TestCrearYVincularCuenta(TestCase):

    def setUp(self):
        self.creator = _make_creator('cv')
        self.paciente = _make_paciente(
            self.creator, 'HC020',
            nombre='María', apellido='Torres',
            tipo_documento='DNI', numero_documento='12345678',
        )

    @patch('core.email_service.send_mail')
    def test_crea_usuario_y_lo_vincula(self, _):
        user = crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        self.paciente.refresh_from_db()
        self.assertIsNotNone(user)
        self.assertEqual(self.paciente.usuario_cuenta, user)

    @patch('core.email_service.send_mail')
    def test_usuario_tiene_grupo_paciente(self, _):
        user = crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        self.assertTrue(user.groups.filter(name='paciente').exists())

    @patch('core.email_service.send_mail')
    def test_perfil_must_change_password_es_true(self, _):
        user = crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        profile = UserProfile.objects.get(user=user)
        self.assertTrue(profile.must_change_password)

    @patch('core.email_service.send_mail')
    def test_perfil_email_verified_es_false(self, _):
        user = crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        profile = UserProfile.objects.get(user=user)
        self.assertFalse(profile.email_verified)

    @patch('core.email_service.send_mail')
    def test_perfil_copia_documento_del_paciente(self, _):
        user = crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.numero_documento, '12345678')
        self.assertEqual(profile.tipo_documento, 'DNI')

    @patch('core.email_service.send_mail')
    def test_nombre_y_apellido_heredados_del_paciente(self, _):
        user = crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        self.assertEqual(user.first_name, 'María')
        self.assertEqual(user.last_name, 'Torres')

    @patch('core.email_service.send_mail')
    def test_usuario_puede_autenticarse_con_password(self, _):
        crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        user = User.objects.get(email='maria@test.com')
        self.assertTrue(user.check_password('segura123'))

    def test_raises_valor_error_si_password_menor_a_6_chars(self):
        with self.assertRaises(ValueError):
            crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'abc')

    def test_raises_valor_error_si_password_vacia(self):
        with self.assertRaises(ValueError):
            crear_y_vincular_cuenta(self.paciente, 'maria@test.com', '')

    @patch('core.email_service.send_mail', side_effect=Exception('SMTP down'))
    def test_fallo_de_email_no_propaga_excepcion(self, _):
        try:
            crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        except Exception:
            self.fail('crear_y_vincular_cuenta no debe propagar errores de envío de email')

    @patch('core.email_service.send_mail', side_effect=Exception('SMTP down'))
    def test_paciente_queda_vinculado_aunque_email_falle(self, _):
        user = crear_y_vincular_cuenta(self.paciente, 'maria@test.com', 'segura123')
        self.paciente.refresh_from_db()
        self.assertEqual(self.paciente.usuario_cuenta, user)


# ---------------------------------------------------------------------------
# _unique_username
# ---------------------------------------------------------------------------

class TestUniqueUsername(TestCase):

    def test_base_disponible_retorna_base(self):
        self.assertEqual(_unique_username('juanperez'), 'juanperez')

    def test_conflicto_unico_agrega_sufijo_1(self):
        User.objects.create_user(username='juan', password='x', email='j1@test.com')
        self.assertEqual(_unique_username('juan'), 'juan1')

    def test_multiples_conflictos_incrementa_contador(self):
        for i, email in enumerate(['c1@t.com', 'c2@t.com', 'c3@t.com'], start=0):
            suffix = str(i) if i else ''
            User.objects.create_user(username=f'carlos{suffix}', password='x', email=email)
        self.assertEqual(_unique_username('carlos'), 'carlos3')

    def test_base_muy_larga_no_trunca(self):
        base = 'x' * 50
        result = _unique_username(base)
        self.assertEqual(result, base)
