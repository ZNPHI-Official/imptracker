from django.contrib import admin

from .models import Settings


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Email Notifications', {'fields': ('email_notifications_enabled', 'notification_email')}),
        ('Booking', {'fields': ('buffer_days',)}),
        ('Coordination Nudge', {'fields': ('nudge_mode', 'nudge_custom_days')}),
        ('Maintenance', {'fields': ('default_maintenance_interval_km',)}),
    )

    def has_add_permission(self, request):
        return not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
