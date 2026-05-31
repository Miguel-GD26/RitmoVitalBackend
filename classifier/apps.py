from django.apps import AppConfig


class ClassifierConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'classifier'

    def ready(self):
        # TF se carga bajo demanda en la primera petición (MLService.initialize()
        # es idempotente y thread-safe con double-check locking).
        #
        # NO pre-cargamos en startup porque Railway hace rolling deploys:
        # el nuevo contenedor arranca mientras el viejo aún está corriendo.
        # Si ambos cargaran TF simultáneamente (~200MB cada uno) superarían
        # el límite de ~512MB del free tier y el OOM killer mataría el proceso.
        # Sin pre-carga, el nuevo contenedor sólo usa ~80MB (Django), pasa el
        # health check, Railway elimina el viejo, y entonces TF carga solo
        # para el primer request real (~2s, modelo 17.6MB).
        pass
