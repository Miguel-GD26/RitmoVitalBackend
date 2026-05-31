"""
Instancia de Celery para el proyecto cardioweb.
Workers: celery -A cardioweb worker -l info
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cardioweb.settings')
os.environ.setdefault('DJANGO_ENV', 'development')

app = Celery('cardioweb')
app.config_from_object('django.conf:settings', namespace='CELERY')

# Discovery explícita: tasks/ es un paquete, no un módulo plano
app.autodiscover_tasks(['classifier'])
