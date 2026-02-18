from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from masters.models import ActivityStatus, Currency, ProcurementType

# Default reference data
DEFAULT_STATUSES = [
    {"name": "Planned", "is_default": True},
    {"name": "In Progress", "is_default": False},
    {"name": "Partially Implemented", "is_default": False},
    {"name": "Fully Implemented", "is_default": False},
    {"name": "Cancelled", "is_default": False},
]

DEFAULT_CURRENCIES = [
    {"code": "ZMW", "name": "Zambian Kwacha", "symbol": "ZK", "is_default": True},
    {"code": "USD", "name": "US Dollar", "symbol": "$", "is_default": False},
]

DEFAULT_PROCUREMENT_TYPES = [
    {"code": "equipment", "name": "Equipment", "is_default": True},
    {"code": "services", "name": "Services", "is_default": False},
    {"code": "supplies", "name": "Supplies", "is_default": False},
    {"code": "venue", "name": "Venue/Logistics", "is_default": False},
    {"code": "staff", "name": "Staff", "is_default": False},
    {"code": "other", "name": "Other", "is_default": False},
]

DEFAULT_GROUPS = {
    "System Admin": "all",
    "User Manager": [
        "accounts.user",
        "accounts.cluster",
    ],
    "Data Manager": [
        "activities.activity",
        "activities.activityattachment",
        "activities.notificationlog",
        "masters.funder",
        "masters.activitystatus",
        "masters.currency",
        "masters.procurementtype",
        "uploads.uploadbatch",
    ],
    "Project Coordinator": [
        "activities.activity",
        "activities.activityattachment",
        "activities.notificationlog",
        "masters.funder",
        "masters.activitystatus",
        "masters.currency",
        "masters.procurementtype",
        "uploads.uploadbatch",
    ],
    "Activity Manager": [
        "activities.activity",
        "activities.activityattachment",
    ],
    "Viewer": [
        "activities.activity",
        "activities.activityattachment",
        "activities.notificationlog",
        "masters.funder",
        "masters.activitystatus",
        "masters.currency",
        "masters.procurementtype",
        "audit.auditlog",
    ],
}


class Command(BaseCommand):
    help = "Seed baseline roles, permissions, and master data"

    def handle(self, *args, **options):
        with transaction.atomic():
            self._seed_statuses()
            self._seed_currencies()
            self._seed_procurement_types()
            self._seed_groups()
        self.stdout.write(self.style.SUCCESS("Default data seeding complete."))

    def _seed_statuses(self):
        for status in DEFAULT_STATUSES:
            obj, created = ActivityStatus.objects.get_or_create(
                name=status["name"],
                defaults={"is_default": status["is_default"]},
            )
            if not created and obj.is_default != status["is_default"]:
                obj.is_default = status["is_default"]
                obj.save(update_fields=["is_default"])
            self.stdout.write(f"Status: {obj.name} ({'created' if created else 'exists'})")

    def _seed_currencies(self):
        for currency in DEFAULT_CURRENCIES:
            obj, created = Currency.objects.get_or_create(
                code=currency["code"],
                defaults={
                    "name": currency["name"],
                    "symbol": currency["symbol"],
                    "is_default": currency["is_default"],
                },
            )
            if not created:
                updated_fields = []
                for field in ["name", "symbol", "is_default"]:
                    if getattr(obj, field) != currency[field]:
                        setattr(obj, field, currency[field])
                        updated_fields.append(field)
                if updated_fields:
                    obj.save(update_fields=updated_fields)
            self.stdout.write(f"Currency: {obj.code} ({'created' if created else 'updated'})")

    def _seed_procurement_types(self):
        for entry in DEFAULT_PROCUREMENT_TYPES:
            obj, created = ProcurementType.objects.get_or_create(
                code=entry["code"],
                defaults={
                    "name": entry["name"],
                    "active": True,
                    "is_default": entry["is_default"],
                },
            )
            if not created and obj.is_default != entry["is_default"]:
                obj.is_default = entry["is_default"]
                obj.save(update_fields=["is_default"])
            self.stdout.write(f"Procurement Type: {obj.name} ({'created' if created else 'exists'})")

    def _seed_groups(self):
        for group_name, model_list in DEFAULT_GROUPS.items():
            group, created = Group.objects.get_or_create(name=group_name)
            if model_list == "all":
                perms = Permission.objects.all()
            else:
                perms = self._collect_permissions(model_list)
            group.permissions.set(perms)
            group.save()
            perm_count = perms.count() if hasattr(perms, 'count') else len(perms)
            self.stdout.write(f"Group: {group.name} ({'created' if created else 'updated'}) with {perm_count} perms")

    def _collect_permissions(self, model_labels):
        from django.db.models import Q
        q_objects = Q()
        for label in model_labels:
            app_label, model_name = label.split(".")
            try:
                content_type = ContentType.objects.get(app_label=app_label, model=model_name.lower())
                q_objects |= Q(content_type=content_type)
            except ContentType.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"ContentType not found: {app_label}.{model_name}"))
        return Permission.objects.filter(q_objects)
