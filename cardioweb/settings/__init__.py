"""
Selecciona la configuración según la variable de entorno DJANGO_ENV.
  DJANGO_ENV=production  → production.py
  (default)              → development.py
"""
import os

_env = os.environ.get('DJANGO_ENV', 'development')

if _env == 'production':
    from cardioweb.settings.production import *  # noqa: F401, F403
else:
    from cardioweb.settings.development import *  # noqa: F401, F403
