"""
classifier.views — re-exporta todas las vistas para compatibilidad con urls.py.

Implementaciones en sub-módulos:
  analysis  → ClassifyRandomView, AnalyzePatientView, AnalyzePatientProductionView
  history   → AnalysisHistoryView, AnalysisPdfView, AnalysisCsvExportView
  dashboard → DashboardStatsView
  patients  → PatientListView, PatientDetailView
  infra     → ModelInfoView, HealthCheckView
"""

from classifier.views.analysis import (
    ClassifyRandomView,
    AnalyzePatientView,
    AnalyzePatientProductionView,
    AnalysisStatusView,
)
from classifier.views.history import (
    AnalysisHistoryView,
    AnalysisPdfView,
    AnalysisCsvExportView,
)
from classifier.views.dashboard import DashboardStatsView
from classifier.views.patients import PatientListView, PatientDetailView, PatientVincularView
from classifier.views.infra import ModelInfoView, HealthCheckView

__all__ = [
    'ClassifyRandomView',
    'AnalyzePatientView',
    'AnalyzePatientProductionView',
    'AnalysisStatusView',
    'AnalysisHistoryView',
    'AnalysisPdfView',
    'AnalysisCsvExportView',
    'DashboardStatsView',
    'PatientListView',
    'PatientDetailView',
    'PatientVincularView',
    'ModelInfoView',
    'HealthCheckView',
]
