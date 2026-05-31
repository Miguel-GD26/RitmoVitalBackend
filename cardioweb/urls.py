"""URL configuration for cardioweb project."""

from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from core.auth_views import (
    CookieLoginView, CookieRefreshView, LogoutView, CurrentUserView, GoogleAuthView,
    Verify2FAView, TOTPSetupView,
)
from core.lookup_view import DocumentoLookupView
from core.admin_views import (
    AdminUserListView, AdminUserDetailView, AdminUserAvatarView,
    AdminRoleListView, AdminRoleUpdateView, AdminPermissionListView,
)
from classifier.urls import v1_urlpatterns, infra_urlpatterns

urlpatterns = [
    path('admin/', admin.site.urls),

    # ---------------------------------------------------------------------------
    # Auth — rutas canónicas versionadas (/api/v1/auth/)
    # ---------------------------------------------------------------------------
    path('api/v1/auth/login/',      CookieLoginView.as_view(),  name='v1_token_obtain_pair'),
    path('api/v1/auth/refresh/',    CookieRefreshView.as_view(), name='v1_token_refresh'),
    path('api/v1/auth/logout/',     LogoutView.as_view(),        name='v1_token_logout'),
    path('api/v1/auth/me/',         CurrentUserView.as_view(),   name='v1_current_user'),
    path('api/v1/auth/google/',     GoogleAuthView.as_view(),    name='v1_google_auth'),
    path('api/v1/auth/2fa/verify/', Verify2FAView.as_view(),     name='v1_2fa_verify'),
    path('api/v1/auth/2fa/setup/',  TOTPSetupView.as_view(),     name='v1_2fa_setup'),

    # ---------------------------------------------------------------------------
    # Auth — alias sin versión mantenidos por backward-compat (deprecar en v2)
    # ---------------------------------------------------------------------------
    path('api/auth/login/', CookieLoginView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', CookieRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='token_logout'),
    path('api/auth/me/', CurrentUserView.as_view(), name='current_user'),
    path('api/auth/google/', GoogleAuthView.as_view(), name='google_auth'),
    path('api/auth/2fa/verify/', Verify2FAView.as_view(), name='2fa_verify'),
    path('api/auth/2fa/setup/',  TOTPSetupView.as_view(),  name='2fa_setup'),

    # ---------------------------------------------------------------------------
    # Admin — gestión de usuarios y roles (solo superusuarios)
    # ---------------------------------------------------------------------------
    path('api/v1/admin/users/',       AdminUserListView.as_view(),   name='admin_users'),
    path('api/v1/admin/users/<uuid:uuid>/', AdminUserDetailView.as_view(), name='admin_user_detail'),
    path('api/v1/admin/users/<uuid:uuid>/avatar/', AdminUserAvatarView.as_view(), name='admin_user_avatar'),
    path('api/v1/admin/roles/',            AdminRoleListView.as_view(),   name='admin_roles'),
    path('api/v1/admin/roles/<int:pk>/',   AdminRoleUpdateView.as_view(), name='admin_role_update'),
    path('api/v1/admin/permissions/',      AdminPermissionListView.as_view(), name='admin_permissions'),

    # ---------------------------------------------------------------------------
    # Lookup de documento (DNI/CE/RUC) — médico y admin
    # ---------------------------------------------------------------------------
    path('api/v1/lookup/documento/', DocumentoLookupView.as_view(), name='lookup_documento'),

    # ---------------------------------------------------------------------------
    # API v1 — endpoints de negocio versionados
    # ---------------------------------------------------------------------------
    path('api/v1/', include((v1_urlpatterns, 'v1'))),

    # ---------------------------------------------------------------------------
    # Infraestructura — health check y model info (sin versión)
    # ---------------------------------------------------------------------------
    *infra_urlpatterns,

    # ---------------------------------------------------------------------------
    # Swagger / OpenAPI
    # ---------------------------------------------------------------------------
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger_ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
