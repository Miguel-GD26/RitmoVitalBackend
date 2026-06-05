"""
classifier.services.file_service — Gestión segura de archivos ECG (sesiones, validación, sanitización).
"""

import os
import uuid
import shutil
import logging

import requests as http_requests
from django.conf import settings
from django.core.files.storage import FileSystemStorage

from classifier.constants import (
    ALLOWED_ECG_EXTENSIONS,
    MAX_ECG_FILE_SIZE_BYTES,
    MAX_ECG_FILE_SIZE_MB,
)
from core.exceptions import FileValidationError

logger = logging.getLogger(__name__)


class FileService:
    """Servicio stateless para gestión segura de archivos ECG."""

    # ------------------------------------------------------------------
    # Gestión de sesiones (directorios temporales)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_upload_base_dir():
        """Obtiene (y crea si no existe) el directorio base de uploads."""
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        return upload_dir

    @staticmethod
    def create_session():
        """Crea directorio temporal de sesión. Retorna (session_id, session_dir_path)."""
        session_id = str(uuid.uuid4())[:16]
        session_dir = os.path.join(
            FileService._get_upload_base_dir(), session_id
        )
        os.makedirs(session_dir, exist_ok=True)
        logger.debug("Sesión creada: %s", session_id)
        return session_id, session_dir

    @staticmethod
    def cleanup_session(session_dir):
        """Elimina el directorio de sesión. Nunca lanza excepciones — solo loguea warnings."""
        if session_dir and os.path.exists(session_dir):
            try:
                shutil.rmtree(session_dir)
                logger.debug("Sesión limpiada: %s", session_dir)
            except Exception as e:
                logger.warning(
                    "No se pudo limpiar sesión %s: %s", session_dir, e
                )

    # ------------------------------------------------------------------
    # Validación de archivos
    # ------------------------------------------------------------------

    @staticmethod
    def validate_ecg_file(uploaded_file):
        """Valida extensión, tamaño y nombre (prevención path traversal). Raises FileValidationError."""
        original_name = uploaded_file.name

        # 1. Sanitizar nombre — prevenir path traversal
        safe_name = os.path.basename(original_name)
        if not safe_name or safe_name != original_name:
            raise FileValidationError(
                detail=f"Nombre de archivo no permitido: '{original_name}'"
            )

        # 2. Validar extensión
        _, ext = os.path.splitext(safe_name)
        if ext.lower() not in ALLOWED_ECG_EXTENSIONS:
            raise FileValidationError(
                detail=(
                    f"Extensión '{ext}' no permitida. "
                    f"Extensiones válidas: {', '.join(sorted(ALLOWED_ECG_EXTENSIONS))}"
                )
            )

        # 3. Validar tamaño
        if uploaded_file.size > MAX_ECG_FILE_SIZE_BYTES:
            raise FileValidationError(
                detail=(
                    f"Archivo '{safe_name}' excede el tamaño máximo "
                    f"de {MAX_ECG_FILE_SIZE_MB}MB"
                )
            )

        return safe_name

    # ------------------------------------------------------------------
    # Guardado de archivos
    # ------------------------------------------------------------------

    @staticmethod
    def save_ecg_files_annotated(files_dict, session_dir):
        """Guarda .dat/.atr/.hea en session_dir. Retorna el nombre base del registro."""
        fs = FileSystemStorage(location=session_dir)

        for key in ('dat_file', 'atr_file', 'hea_file'):
            uploaded = files_dict.get(key)
            if uploaded is not None:
                safe_name = FileService.validate_ecg_file(uploaded)
                fs.save(safe_name, uploaded)

        dat_file = files_dict.get('dat_file')
        if dat_file is None:
            raise FileValidationError(
                detail="Se requiere al menos el archivo .dat"
            )

        record_name = os.path.splitext(os.path.basename(dat_file.name))[0]
        return record_name

    @staticmethod
    def save_ecg_files_production(dat_file, hea_file, session_dir):
        """Guarda .dat/.hea en session_dir. Retorna el nombre base del registro."""
        fs = FileSystemStorage(location=session_dir)

        for uploaded in (dat_file, hea_file):
            safe_name = FileService.validate_ecg_file(uploaded)
            fs.save(safe_name, uploaded)

        record_name = os.path.splitext(os.path.basename(dat_file.name))[0]
        return record_name

    @staticmethod
    def get_record_path(session_dir, record_name):
        """Construye la ruta base del registro dentro del directorio de sesión."""
        return os.path.join(session_dir, record_name)

    # ------------------------------------------------------------------
    # Cloudinary — transferencia entre contenedores
    # ------------------------------------------------------------------

    @staticmethod
    def upload_ecg_to_cloudinary(session_dir: str) -> dict:
        """
        Sube todos los archivos de session_dir a Cloudinary como raw.
        Retorna {filename: secure_url}. Requiere CLOUDINARY_ENABLED=True.
        """
        import cloudinary.uploader

        session_id = os.path.basename(session_dir)
        urls: dict = {}
        for fname in os.listdir(session_dir):
            fpath = os.path.join(session_dir, fname)
            if not os.path.isfile(fpath):
                continue
            result = cloudinary.uploader.upload(
                fpath,
                resource_type='raw',
                folder=f'ritmovital/ecg_sessions/{session_id}',
                public_id=fname,
                use_filename=True,
                unique_filename=False,
                overwrite=True,
            )
            urls[fname] = result['secure_url']
            logger.debug("Subido a Cloudinary: %s → %s", fname, urls[fname])
        return urls

    @staticmethod
    def download_ecg_from_cloudinary(cloudinary_urls: dict, session_dir: str) -> None:
        """Descarga archivos ECG desde URLs de Cloudinary al session_dir local (streaming)."""
        os.makedirs(session_dir, exist_ok=True)
        for fname, url in cloudinary_urls.items():
            dest = os.path.join(session_dir, fname)
            with http_requests.get(url, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with open(dest, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            logger.debug("Descargado desde Cloudinary: %s", fname)
