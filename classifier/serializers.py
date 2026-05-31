"""
classifier.serializers — Serializers DRF para validación de entrada.
"""

from rest_framework import serializers

from classifier.constants import ALLOWED_ECG_EXTENSIONS
from classifier.models import AnalisisECG, Paciente


class BeatIndexInputSerializer(serializers.Serializer):

    beat_index = serializers.IntegerField(
        required=True,
        min_value=0,
        help_text="Índice del latido en el dataset de prueba (0-indexed)",
    )


class AnalyzePatientSerializer(serializers.Serializer):

    dat_file = serializers.FileField(
        required=True,
        help_text="Archivo de señal MIT-BIH (.dat)",
    )
    atr_file = serializers.FileField(
        required=True,
        help_text="Archivo de anotaciones MIT-BIH (.atr)",
    )
    hea_file = serializers.FileField(
        required=True,
        help_text="Archivo header MIT-BIH (.hea)",
    )


class AnalyzePatientProductionSerializer(serializers.Serializer):

    dat_file = serializers.FileField(
        required=True,
        help_text="Archivo de señal ECG (.dat)",
    )
    hea_file = serializers.FileField(
        required=True,
        help_text="Archivo header ECG (.hea)",
    )


class PaginationInputSerializer(serializers.Serializer):

    page = serializers.IntegerField(
        required=False,
        default=1,
        min_value=1,
        help_text="Número de página (1-indexed)",
    )
    page_size = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=500,
        help_text="Número de items por página (máximo 500)",
    )


class AnalisisECGSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.SerializerMethodField()
    paciente_nombre = serializers.SerializerMethodField()
    modo_display = serializers.CharField(source='get_modo_display', read_only=True)

    class Meta:
        model = AnalisisECG
        fields = [
            'id', 'uuid', 'usuario_nombre', 'paciente', 'paciente_nombre', 'record_name',
            'modo', 'modo_display', 'fecha', 'total_latidos', 'latidos_procesados',
            'accuracy', 'modelo_version',
        ]

    def get_usuario_nombre(self, obj):
        return obj.usuario.username if obj.usuario else 'Sistema'

    def get_paciente_nombre(self, obj):
        if not obj.paciente:
            return None
        return f"{obj.paciente.nombre} {obj.paciente.apellido}"


class PacienteSerializer(serializers.ModelSerializer):
    creado_por_nombre = serializers.SerializerMethodField()
    total_analisis    = serializers.SerializerMethodField()
    usuario_uuid      = serializers.SerializerMethodField()

    class Meta:
        model = Paciente
        fields = [
            'id', 'uuid', 'nombre', 'apellido', 'fecha_nacimiento', 'sexo',
            'tipo_documento', 'numero_documento',
            'historia_clinica', 'notas', 'creado_por_nombre', 'fecha_registro',
            'total_analisis', 'usuario_uuid',
        ]
        read_only_fields = ['id', 'uuid', 'creado_por_nombre', 'fecha_registro', 'total_analisis', 'usuario_uuid']

    def get_creado_por_nombre(self, obj):
        return obj.creado_por.username if obj.creado_por else None

    def get_total_analisis(self, obj):
        return obj.analisis.count()

    def get_usuario_uuid(self, obj):
        if not obj.usuario_cuenta:
            return None
        try:
            return str(obj.usuario_cuenta.profile.uuid)
        except Exception:
            return None


class PacienteWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paciente
        fields = ['nombre', 'apellido', 'fecha_nacimiento', 'sexo',
                  'tipo_documento', 'numero_documento', 'historia_clinica', 'notas']