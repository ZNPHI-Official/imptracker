from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'
    # 'dashboard' is already taken by jet.dashboard; this app has no models,
    # so relabeling is safe.
    label = 'fleet_dashboard'
