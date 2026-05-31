# Backward-compat shim — all functions moved to dedicated service modules.
# Import from the new locations directly in new code.
from classifier.services.signal_processing import (  # noqa: F401
    apply_cwt,
    calculate_rr_features,
    bandpass_filter,
    correct_r_peaks,
    detect_r_peaks_automatic,
)
from classifier.services.ecg_reader import (  # noqa: F401
    procesar_archivo_mitbih,
    procesar_archivo_mitbih_produccion,
)
