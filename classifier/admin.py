from django.contrib import admin

from classifier.models import AnalisisECG, AuditLog, Paciente


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('apellido', 'nombre', 'sexo', 'fecha_nacimiento', 'historia_clinica', 'fecha_registro')
    list_filter = ('sexo',)
    search_fields = ('nombre', 'apellido', 'historia_clinica')
    readonly_fields = ('fecha_registro',)


@admin.register(AnalisisECG)
class AnalisisECGAdmin(admin.ModelAdmin):
    list_display = ('record_name', 'paciente', 'usuario', 'modo', 'total_latidos', 'latidos_procesados', 'accuracy', 'fecha')
    list_filter = ('modo', 'fecha')
    search_fields = ('record_name', 'usuario__username', 'paciente__apellido')
    readonly_fields = ('fecha',)
    autocomplete_fields = ('paciente',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'usuario', 'accion', 'endpoint', 'ip_address')
    list_filter = ('accion', 'timestamp')
    search_fields = ('usuario__username', 'endpoint')
    readonly_fields = ('timestamp',)
