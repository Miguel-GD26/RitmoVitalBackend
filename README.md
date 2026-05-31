# RitmoVital — Backend

API REST para clasificación de arritmias cardíacas en señales ECG, desarrollada como proyecto de tesis de Ingeniería de Sistemas.

**Universidad:** Universidad Señor de Sipán (USS)  
**Autores:** Percy Gálvez · Miguel García

---

## Stack tecnológico

| Componente | Tecnología |
|---|---|
| Framework | Django 5.2 + Django REST Framework 3.16 |
| Modelo IA | TensorFlow 2.20 / Keras 3.11 — trimodal CNN-LSTM-Atención |
| Base de datos | PostgreSQL |
| Caché / Cola | Redis + Celery |
| Autenticación | JWT HttpOnly Cookies + 2FA TOTP + Google OAuth |
| Almacenamiento | Cloudinary (gráficas ECG) |
| Servidor | Gunicorn (producción) |
| Deploy | Railway — Docker multi-stage |

---

## Configuración local

### 1. Requisitos previos

- Python 3.12
- PostgreSQL corriendo localmente
- Redis corriendo localmente (opcional para desarrollo)

### 2. Instalar dependencias

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac
pip install -r requirements.txt
```

### 3. Variables de entorno

Crear un archivo `.env` en la raíz del backend:

```env
DJANGO_ENV=development

SECRET_KEY=tu-clave-secreta-django

DB_HOST=localhost
DB_NAME=ritmovital
DB_USER=postgres
DB_PASSWORD=tu-password
DB_PORT=5432

# Opcionales en desarrollo
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

### 4. Migraciones y servidor

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

La API queda disponible en `http://localhost:8000`.

---

## Variables de entorno en producción (Railway)

| Variable | Descripción |
|---|---|
| `DJANGO_ENV` | `production` |
| `SECRET_KEY` | Clave secreta Django |
| `DB_HOST` | Host PostgreSQL |
| `DB_NAME` | Nombre de la base de datos |
| `DB_USER` | Usuario PostgreSQL |
| `DB_PASSWORD` | Contraseña PostgreSQL |
| `DB_PORT` | Puerto PostgreSQL |
| `REDIS_URL` | URL de Redis (broker + caché) |
| `FRONTEND_URL` | URL del frontend desplegado |
| `MODEL_URL` | URL de descarga del modelo `.keras` |
| `TEST_DATA_URL` | URL de descarga del dataset de prueba `.csv` |
| `CLOUDINARY_CLOUD_NAME` | Credenciales Cloudinary (opcional) |
| `CLOUDINARY_API_KEY` | |
| `CLOUDINARY_API_SECRET` | |
| `GOOGLE_CLIENT_ID` | OAuth Google (opcional) |
| `GOOGLE_CLIENT_SECRET` | |

---

## Estructura del proyecto

```
backend/
├── cardioweb/
│   ├── settings/
│   │   ├── __init__.py       ← Selecciona config según DJANGO_ENV
│   │   ├── base.py           ← Configuración compartida
│   │   ├── development.py    ← Config local
│   │   └── production.py     ← Config Railway
│   ├── urls.py
│   └── wsgi.py
├── core/                     ← Autenticación, usuarios, pacientes
│   ├── auth_views.py
│   ├── models.py
│   └── ...
├── classifier/               ← Motor de clasificación ECG
│   ├── services/
│   │   ├── ml_service.py     ← Carga y caché del modelo TF
│   │   ├── analysis_orchestrator.py
│   │   └── visualization_service.py
│   ├── views.py
│   └── ...
├── requirements.txt
├── Dockerfile
└── manage.py
```

---

## Modelo de IA

El modelo `ultra_best.keras` es una arquitectura trimodal que procesa simultáneamente:

1. **Señal cruda** — 187 muestras del latido
2. **Escalograma CWT** — imagen 128×128 generada con wavelet Morlet
3. **Features estadísticas** — HRV, amplitud, pendiente

**Clases de salida** (AAMI EC57:2012):

| Clase | Descripción |
|---|---|
| N | Normal |
| S | Supraventricular |
| V | Ventricular |
| F | Fusión |

El modelo se descarga automáticamente desde GitHub Releases al iniciar el servidor en producción.

---

## Endpoints principales

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/auth/login/` | Login con email y contraseña |
| `POST` | `/api/v1/auth/logout/` | Cierre de sesión |
| `POST` | `/api/v1/auth/refresh/` | Renovar token de acceso |
| `GET` | `/api/v1/auth/me/` | Usuario autenticado actual |
| `POST` | `/api/v1/auth/2fa/verify/` | Verificación TOTP |
| `POST` | `/api/v1/auth/google/` | Login con Google OAuth |
| `GET` | `/api/v1/pacientes/` | Listado de pacientes |
| `POST` | `/api/v1/classifier/analyze/` | Analizar ECG de paciente |
| `GET` | `/api/v1/classifier/demo/` | Clasificación demo (latido aleatorio) |
| `GET` | `/api/health/` | Health check |
| `GET` | `/api/schema/` | Esquema OpenAPI |
| `GET` | `/api/docs/` | Swagger UI |

---

## Docker

```bash
# Build
docker build -t ritmovital-backend .

# Correr con variables de entorno
docker run -p 8000:8000 --env-file .env ritmovital-backend
```
