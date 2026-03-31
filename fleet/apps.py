from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _setup_fleet_permissions_after_migrate(sender, **kwargs):
    if sender.name != "fleet":
        return

    from fleet.permissions import setup_fleet_permissions

    try:
        setup_fleet_permissions()
    except Exception:
        pass


class FleetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fleet"
    verbose_name = "Fleet Management"

    def ready(self):
        """Import signals when Django app is ready."""
        import fleet.signals  # noqa
        post_migrate.connect(
            _setup_fleet_permissions_after_migrate,
            dispatch_uid="fleet.setup_permissions.post_migrate"
        )
