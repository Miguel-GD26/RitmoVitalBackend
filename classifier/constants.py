"""
classifier.constants — Constantes centralizadas del dominio ML/ECG.

Todas las constantes de configuración del modelo, mapeos de etiquetas,
y parámetros del pipeline de inferencia se definen aquí para evitar
valores hardcodeados dispersos en views, utils, y services.
"""

# ---------------------------------------------------------------------------
# Dimensiones del modelo tri-modal
# ---------------------------------------------------------------------------

LEN_SIGNAL = 260       # Longitud de la señal ECG (muestras por latido)
LEN_RR = 4             # Número de features RR-interval
IMG_SIZE = 128          # Tamaño del escalograma CWT (IMG_SIZE × IMG_SIZE)

# ---------------------------------------------------------------------------
# Mapeo de etiquetas AAMI EC57:2012 — 4 clases oficiales
# ---------------------------------------------------------------------------

LABELS_MAP = {
    0: "Normal (N)",
    1: "Supraventricular (S)",
    2: "Ventricular (V)",
    3: "Fusión (F)",
}

# ---------------------------------------------------------------------------
# Parámetros CWT (Continuous Wavelet Transform)
# ---------------------------------------------------------------------------

WINDOW_SIZE = 260
CWT_SIZE = 128
WAVELET = 'cmor1.5-1.0'

# ---------------------------------------------------------------------------
# Mapeo de símbolos MIT-BIH a clases AAMI EC57:2012
#
# Clases válidas:  0=Normal, 1=Supraventricular, 2=Ventricular, 3=Fusión
# Clase -1:        Excluidos (no son clases AAMI oficiales)
# ---------------------------------------------------------------------------

AAMI_MAPPING = {
    # Normal (N) — clase 0
    'N': 0, 'L': 0, 'R': 0, 'e': 0, 'j': 0,
    # Supraventricular (S) — clase 1
    'A': 1, 'a': 1, 'J': 1, 'S': 1,
    # Ventricular (V) — clase 2
    'V': 2, 'E': 2,
    # Fusión (F) — clase 3
    'F': 3,
    # Excluidos — NO son clases AAMI oficiales
    '/': -1, 'f': -1, 'Q': -1, '[': -1, '!': -1,
    ']': -1, 'x': -1, '(': -1, ')': -1, 'p': -1,
    't': -1, 'u': -1, '`': -1, "'": -1, '^': -1,
    '|': -1, '~': -1, '+': -1, 's': -1, 'T': -1,
    '*': -1, 'D': -1, '=': -1, '"': -1, '@': -1,
}

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
