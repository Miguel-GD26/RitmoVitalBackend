"""
classifier.constants — Constantes centralizadas del dominio ML/ECG.

Todas las constantes de configuración del modelo, mapeos de etiquetas,
y parámetros del pipeline de inferencia se definen aquí para evitar
valores hardcodeados dispersos en views, utils, y services.

LABELS_MAP y AAMI_MAPPING se cargan desde model_metadata.json (OCP):
actualizar el modelo solo requiere editar el JSON, no el código Python.
"""
import json
import os

# ---------------------------------------------------------------------------
# Dimensiones del modelo tri-modal
# ---------------------------------------------------------------------------

LEN_SIGNAL = 260       # Longitud de la señal ECG (muestras por latido)
LEN_RR = 4             # Número de features RR-interval
IMG_SIZE = 128          # Tamaño del escalograma CWT (IMG_SIZE × IMG_SIZE)

# ---------------------------------------------------------------------------
# Mapeos AAMI EC57:2012 — cargados desde model_metadata.json
# ---------------------------------------------------------------------------

_METADATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'classifier', 'artifacts', 'model_metadata.json',
)

_LABELS_MAP_FALLBACK = {
    0: "Normal (N)",
    1: "Supraventricular (S)",
    2: "Ventricular (V)",
    3: "Fusión (F)",
}

_AAMI_MAPPING_FALLBACK = {
    'N': 0, 'L': 0, 'R': 0, 'e': 0, 'j': 0,
    'A': 1, 'a': 1, 'J': 1, 'S': 1,
    'V': 2, 'E': 2,
    'F': 3,
    '/': -1, 'f': -1, 'Q': -1, '[': -1, '!': -1,
    ']': -1, 'x': -1, '(': -1, ')': -1, 'p': -1,
    't': -1, 'u': -1, '`': -1, "'": -1, '^': -1,
    '|': -1, '~': -1, '+': -1, 's': -1, 'T': -1,
    '*': -1, 'D': -1, '=': -1, '"': -1, '@': -1,
}

try:
    with open(_METADATA_PATH, encoding='utf-8') as _f:
        _meta = json.load(_f)
    LABELS_MAP: dict[int, str] = {int(k): v for k, v in _meta['labels_map'].items()}
    AAMI_MAPPING: dict[str, int] = _meta['aami_mapping']
except (FileNotFoundError, KeyError, ValueError):
    LABELS_MAP = _LABELS_MAP_FALLBACK
    AAMI_MAPPING = _AAMI_MAPPING_FALLBACK

# ---------------------------------------------------------------------------
# Parámetros CWT (Continuous Wavelet Transform)
# ---------------------------------------------------------------------------

WINDOW_SIZE = 260
CWT_SIZE = 128
WAVELET = 'cmor1.5-1.0'

# ---------------------------------------------------------------------------
# Archivos del modelo (relativos a BASE_DIR)
# ---------------------------------------------------------------------------

MODEL_RELATIVE_PATH = 'classifier/artifacts/ultra_best.keras'
TEST_DATA_RELATIVE_PATH = 'classifier/data/mitbih_test_multimodal.csv'

# ---------------------------------------------------------------------------
# Validación de archivos ECG
# ---------------------------------------------------------------------------

ALLOWED_ECG_EXTENSIONS = {'.dat', '.atr', '.hea'}
MAX_ECG_FILE_SIZE_MB = 50
MAX_ECG_FILE_SIZE_BYTES = MAX_ECG_FILE_SIZE_MB * 1024 * 1024

# ---------------------------------------------------------------------------
# Umbrales clínicos
# ---------------------------------------------------------------------------

PREMATURE_BEAT_THRESHOLD = 0.88  # ratio pre_rr / local_avg

# ---------------------------------------------------------------------------
# Registros MIT-BIH incompatibles (contienen marcapasos)
# Sirven desde ModelInfoView → el frontend los consume del backend.
# ---------------------------------------------------------------------------

PACEMAKER_RECORDS = ['102', '104', '107', '217']
