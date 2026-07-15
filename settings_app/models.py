from django.db import models


class Settings(models.Model):
    NUDGE_EXACT = 'exact'
    NUDGE_7DAY = '7day'
    NUDGE_CUSTOM = 'custom'
    NUDGE_MODE_CHOICES = [
        (NUDGE_EXACT, 'Exact date overlap only'),
        (NUDGE_7DAY, '7-day window around each trip'),
        (NUDGE_CUSTOM, 'Custom ± days'),
    ]

    # Email
    email_notifications_enabled = models.BooleanField(default=False)
    notification_email = models.EmailField(
        blank=True,
        help_text='Recipient for new-request notifications. Required when email notifications are on.',
    )

    # Booking buffer
    buffer_days = models.PositiveIntegerField(
        default=1,
        help_text='Minimum buffer days between consecutive trips for the same vehicle or driver.',
    )

    # Coordination nudge window
    nudge_mode = models.CharField(
        max_length=10,
        choices=NUDGE_MODE_CHOICES,
        default=NUDGE_7DAY,
        help_text='Date window that triggers the coordination nudge when trips overlap.',
    )
    nudge_custom_days = models.PositiveIntegerField(
        default=7,
        help_text='Used only when nudge mode is "Custom ± days".',
    )

    # Maintenance
    default_maintenance_interval_km = models.PositiveIntegerField(
        default=5000,
        help_text='Default km interval between services applied to newly added vehicles.',
    )

    class Meta:
        verbose_name = 'Settings'
        verbose_name_plural = 'Settings'

    def save(self, *args, **kwargs):
        # Enforce singleton: always write to pk=1 so there is exactly one row.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Return the singleton Settings row, creating it with defaults if absent."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def nudge_window_days(self):
        """Effective nudge window in days based on the selected mode."""
        if self.nudge_mode == self.NUDGE_EXACT:
            return 0
        if self.nudge_mode == self.NUDGE_CUSTOM:
            return self.nudge_custom_days
        return 7  # NUDGE_7DAY default

    def __str__(self):
        return 'System Settings'
