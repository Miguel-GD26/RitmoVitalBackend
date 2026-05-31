"""Configuración para desarrollo local."""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOW_BEARER_FALLBACK = True

JWT_COOKIE_SECURE = False
JWT_COOKIE_SAMESITE = 'Lax'

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

CORS_ALLOWED_ORIGINS = [
    'http://localhost:4200',
    'http://127.0.0.1:4200',
]
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:4200',
]
CORS_ALLOW_CREDENTIALS = True

# BrowsableAPIRenderer solo en desarrollo
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
}

# Cache en memoria para desarrollo (sin Redis)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Celery — modo síncrono en desarrollo (sin worker externo)
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
