from django import forms

from .models import Settings


class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        fields = [
            'email_notifications_enabled',
            'notification_email',
            'buffer_days',
            'nudge_mode',
            'nudge_custom_days',
            'default_maintenance_interval_km',
        ]
        widgets = {
            'email_notifications_enabled': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary'}),
            'notification_email': forms.EmailInput(attrs={'class': 'input input-bordered w-full', 'placeholder': 'fleet.manager@znphi.gov.zm'}),
            'buffer_days': forms.NumberInput(attrs={'class': 'input input-bordered w-24', 'min': 0, 'max': 30}),
            'nudge_mode': forms.Select(attrs={'class': 'select select-bordered w-full'}),
            'nudge_custom_days': forms.NumberInput(attrs={'class': 'input input-bordered w-24', 'min': 0, 'max': 90}),
            'default_maintenance_interval_km': forms.NumberInput(attrs={'class': 'input input-bordered w-32', 'min': 1000, 'step': 500}),
        }
