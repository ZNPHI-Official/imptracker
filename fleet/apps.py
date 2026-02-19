from django.apps import AppConfig


class FleetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fleet"
    verbose_name = "Fleet Management"

    def ready(self):
        """Import signals when Django app is ready."""
        import fleet.signals  # noqa
        from fleet.permissions import setup_fleet_permissions
        
        # Setup permissions and groups on app ready
        try:
            setup_fleet_permissions()
        except Exception:
            # Handle database not ready during migrations
            pass
