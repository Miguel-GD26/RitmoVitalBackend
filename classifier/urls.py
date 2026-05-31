from django.urls import path

from classifier.views import (
    ClassifyRandomView,
    AnalyzePatientView,
    AnalyzePatientProductionView,
    AnalysisStatusView,
    ModelInfoView,
    HealthCheckView,
    AnalysisHistoryView,
    AnalysisPdfView,
    AnalysisCsvExportView,
    DashboardStatsView,
    PatientListView,
    PatientDetailView,
    PatientVincularView,
)

# Endpoints versionados bajo /api/v1/
v1_urlpatterns = [
    path('classify-random/', ClassifyRandomView.as_view(), name='v1_classify_random'),
    path('analyze-patient/', AnalyzePatientView.as_view(), name='v1_analyze_patient'),
    path('analyze-patient-production/', AnalyzePatientProductionView.as_view(), name='v1_analyze_patient_production'),
    path('analysis/status/<str:task_id>/', AnalysisStatusView.as_view(), name='v1_analysis_status'),
    path('history/', AnalysisHistoryView.as_view(), name='v1_history'),
    path('history/export/csv/', AnalysisCsvExportView.as_view(), name='v1_history_csv_export'),
    path('history/<uuid:uuid>/pdf/', AnalysisPdfView.as_view(), name='v1_analysis_pdf'),
    path('dashboard/', DashboardStatsView.as_view(), name='v1_dashboard'),
    path('patients/', PatientListView.as_view(), name='v1_patients'),
    path('patients/<uuid:uuid>/', PatientDetailView.as_view(), name='v1_patient_detail'),
    path('patients/<uuid:uuid>/vincular/', PatientVincularView.as_view(), name='v1_patient_vincular'),
]

# Endpoints de infraestructura (sin versión)
infra_urlpatterns = [
    path(
        'api/health/',
        HealthCheckView.as_view(),
        name='health_check',
    ),
    path(
        'api/model-info/',
        ModelInfoView.as_view(),
        name='model_info',
    ),
]
