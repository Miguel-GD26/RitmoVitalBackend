"""Configuración para producción (Railway)."""
import os

from .base import *  # noqa: F401, F403

DEBUG = False
# Bearer fallback deshabilitado permanentemente en producción.
# El env var se ignora intencionalmente — la protección HttpOnly no puede
# depender de que nadie olvide setear una variable de entorno.
ALLOW_BEARER_FALLBACK = False

JWT_COOKIE_SECURE = True
JWT_COOKIE_SAMESITE = 'None'

# Hosts fijos + Railway dynamic domain
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'ritmo-vital.up.railway.app']

for _rv in ('RAILWAY_PUBLIC_DOMAIN', 'RAILWAY_STATIC_URL'):
    _rval = os.environ.get(_rv, '').strip()
    if _rval:
        _clean = _rval.replace('https://', '').replace('http://', '').split('/')[0]
        if _clean:
            ALLOWED_HOSTS.append(_clean)

_EXTRA_HOSTS = os.environ.get('ALLOWED_HOSTS_EXTRA', '')
if _EXTRA_HOSTS:
    ALLOWED_HOSTS.extend(h.strip() for h in _EXTRA_HOSTS.split(',') if h.strip())

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://ritmovital.up.railway.app')

CORS_ALLOWED_ORIGINS = [
    'https://ritmovital.up.railway.app',
    FRONTEND_URL,
]
CSRF_TRUSTED_ORIGINS = [
    'https://ritmovital.up.railway.app',
    FRONTEND_URL,
]
CORS_ALLOW_CREDENTIALS = True

# Redis — compartido por cache y Celery
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Celery — broker y result backend en Redis
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = f'redis://{REDIS_URL.split("://", 1)[-1]}'
CELERY_TASK_ALWAYS_EAGER = False

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'IGNORE_EXCEPTIONS': True,
        },
        'KEY_PREFIX': 'ritmovital',
        'TIMEOUT': 300,
    }
}

# Sentry
_SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if _SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=0.1,
        environment='production',
    )
