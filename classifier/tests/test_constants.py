"""
Tests de las constantes del módulo classifier.

Verifica que los valores de AAMI_MAPPING, PACEMAKER_RECORDS y las
constantes numéricas de señal/imagen coincidan con la especificación
AAMI EC57:2012 y con el modelo tri-modal (CWT 128×128, señal 260, RR 4).
"""

from django.test import SimpleTestCase

from classifier.constants import (
    LEN_SIGNAL,
    LEN_RR,
    IMG_SIZE,
    CWT_SIZE,
    WINDOW_SIZE,
    WAVELET,
    AAMI_MAPPING,
    PACEMAKER_RECORDS,
    LABELS_MAP,
)


class SignalConstantsTests(SimpleTestCase):
    """Valores numéricos que alimentan el modelo tri-modal."""

    def test_len_signal(self):
        self.assertEqual(LEN_SIGNAL, 260)

    def test_len_rr(self):
        self.assertEqual(LEN_RR, 4)

    def test_img_size(self):
        self.assertEqual(IMG_SIZE, 128)

    def test_cwt_size(self):
        self.assertEqual(CWT_SIZE, 128)

    def test_window_size(self):
        self.assertEqual(WINDOW_SIZE, 260)

    def test_wavelet(self):
        self.assertEqual(WAVELET, 'cmor1.5-1.0')


class LabelsMapTests(SimpleTestCase):
    """Mapeo de índice de clase a etiqueta legible."""

    def test_normal_label(self):
        self.assertEqual(LABELS_MAP[0], "Normal (N)")

    def test_supraventricular_label(self):
        self.assertEqual(LABELS_MAP[1], "Supraventricular (S)")

    def test_ventricular_label(self):
        self.assertEqual(LABELS_MAP[2], "Ventricular (V)")

    def test_fusion_label(self):
        self.assertEqual(LABELS_MAP[3], "Fusión (F)")


class AamiMappingNormalTests(SimpleTestCase):
    """Clase 0 — Normal (N, L, R, e, j) según AAMI EC57:2012."""

    def test_N_is_normal(self):
        self.assertEqual(AAMI_MAPPING['N'], 0)

    def test_L_is_normal(self):
        self.assertEqual(AAMI_MAPPING['L'], 0)

    def test_R_is_normal(self):
        self.assertEqual(AAMI_MAPPING['R'], 0)

    def test_e_is_normal(self):
        self.assertEqual(AAMI_MAPPING['e'], 0)

    def test_j_is_normal(self):
        self.assertEqual(AAMI_MAPPING['j'], 0)


class AamiMappingSupraventricularTests(SimpleTestCase):
    """Clase 1 — Supraventricular (A, a, J, S) según AAMI EC57:2012."""

    def test_A_is_supraventricular(self):
        self.assertEqual(AAMI_MAPPING['A'], 1)

    def test_a_is_supraventricular(self):
        self.assertEqual(AAMI_MAPPING['a'], 1)

    def test_J_is_supraventricular(self):
        self.assertEqual(AAMI_MAPPING['J'], 1)

    def test_S_is_supraventricular(self):
        self.assertEqual(AAMI_MAPPING['S'], 1)


class AamiMappingVentricularTests(SimpleTestCase):
    """Clase 2 — Ventricular (V, E) según AAMI EC57:2012."""

    def test_V_is_ventricular(self):
        self.assertEqual(AAMI_MAPPING['V'], 2)

    def test_E_is_ventricular(self):
        self.assertEqual(AAMI_MAPPING['E'], 2)


class AamiMappingFusionTests(SimpleTestCase):
    """Clase 3 — Fusión (F) según AAMI EC57:2012."""

    def test_F_is_fusion(self):
        self.assertEqual(AAMI_MAPPING['F'], 3)


class AamiMappingExcludedTests(SimpleTestCase):
    """Clase -1 — símbolos excluidos del análisis estándar."""

    def test_slash_is_excluded(self):
        self.assertEqual(AAMI_MAPPING['/'], -1)

    def test_f_is_excluded(self):
        self.assertEqual(AAMI_MAPPING['f'], -1)

    def test_Q_is_excluded(self):
        self.assertEqual(AAMI_MAPPING['Q'], -1)


class PacemakerRecordsTests(SimpleTestCase):
    """Registros MIT-BIH con marcapasos — excluidos del análisis estándar."""

    def test_pacemaker_records_exact_set(self):
        self.assertEqual(set(PACEMAKER_RECORDS), {'102', '104', '107', '217'})

    def test_pacemaker_records_count(self):
        self.assertEqual(len(PACEMAKER_RECORDS), 4)

    def test_record_102_excluded(self):
        self.assertIn('102', PACEMAKER_RECORDS)

    def test_record_104_excluded(self):
        self.assertIn('104', PACEMAKER_RECORDS)

    def test_record_107_excluded(self):
        self.assertIn('107', PACEMAKER_RECORDS)

    def test_record_217_excluded(self):
        self.assertIn('217', PACEMAKER_RECORDS)

    def test_normal_record_not_excluded(self):
        self.assertNotIn('100', PACEMAKER_RECORDS)
