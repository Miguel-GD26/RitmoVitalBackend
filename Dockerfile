# =============================================================================
# RitmoVital Backend — Dockerfile (Multi-stage, Producción)
# =============================================================================
#
# Build:   docker build -t ritmovital-backend .
# Run:     docker run -p 8000:8000 --env-file .env ritmovital-backend
#
# Variables de entorno requeridas:
#   SECRET_KEY          — Clave secreta Django
#   PORT                — Puerto del servidor (default: 8000)
#   GUNICORN_WORKERS    — Workers Gunicorn (default: 2)
#   GUNICORN_THREADS    — Threads por worker (default: 4)
# =============================================================================

# ---- Stage 1: Instalar dependencias ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Stage 2: Runtime ----
FROM python:3.12-slim

# Crear usuario no-root para seguridad
RUN groupadd -r ritmovital && useradd -r -g ritmovital -d /app ritmovital

WORKDIR /app

# Copiar dependencias pre-instaladas desde stage builder
COPY --from=builder /install /usr/local

# Copiar código fuente
COPY . .

# Crear directorio de media y asignar permisos
RUN mkdir -p media/uploads && chown -R ritmovital:ritmovital /app

# Ejecutar como usuario no-root
USER ritmovital

# Variables de entorno para Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Healthcheck — verifica que Gunicorn responde
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/api/health/')" || exit 1

# Gunicorn con --preload para compartir modelo TF entre workers (ahorra ~500MB RAM)
CMD gunicorn cardioweb.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --timeout 120 \
    --workers ${GUNICORN_WORKERS:-2} \
    --threads ${GUNICORN_THREADS:-4} \
    --preload