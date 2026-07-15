from django import forms

from fleet.models import Driver, Vehicle
from .models import District, TransportRequest


class TransportRequestForm(forms.ModelForm):
    class Meta:
        model = TransportRequest
        fields = [
            'requester_name', 'department', 'position', 'programme_activity',
            'period_from', 'period_to', 'province', 'district',
            'destination', 'num_vehicles', 'num_drivers', 'num_passengers',
            'is_emergency',
        ]
        widgets = {
            'period_from': forms.DateInput(attrs={'type': 'date'}),
            'period_to': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # District choices depend on province; start empty and populate via HTMX or POST data.
        self.fields['district'].queryset = District.objects.none()
        if 'province' in self.data:
            try:
                province_id = int(self.data.get('province'))
                self.fields['district'].queryset = District.objects.filter(province_id=province_id)
            except (ValueError, TypeError):
                pass
        elif self.instance.pk:
            self.fields['district'].queryset = District.objects.filter(province=self.instance.province)

    def clean(self):
        cleaned = super().clean()
        period_from = cleaned.get('period_from')
        period_to = cleaned.get('period_to')
        if period_from and period_to and period_to < period_from:
            raise forms.ValidationError('End date must be on or after the start date.')
        district = cleaned.get('district')
        province = cleaned.get('province')
        if district and province and district.province != province:
            raise forms.ValidationError('Selected district does not belong to the selected province.')
        return cleaned


class RequestApprovalForm(forms.Form):
    admin_comment = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'textarea textarea-bordered w-full'}),
        required=False,
        label='Comment (visible to requester)',
    )

    def __init__(self, *args, num_vehicles=1, available_vehicles=None, available_drivers=None, **kwargs):
        super().__init__(*args, **kwargs)
        vehicle_qs = available_vehicles if available_vehicles is not None else Vehicle.objects.none()
        driver_qs = available_drivers if available_drivers is not None else Driver.objects.none()
        for i in range(1, num_vehicles + 1):
            self.fields[f'vehicle_{i}'] = forms.ModelChoiceField(
                queryset=vehicle_qs,
                label=f'Vehicle {i}',
                empty_label='Select vehicle…',
                widget=forms.Select(attrs={'class': 'select select-bordered w-full'}),
            )
            self.fields[f'driver_{i}'] = forms.ModelChoiceField(
                queryset=driver_qs,
                label=f'Driver {i}',
                empty_label='Select driver…',
                widget=forms.Select(attrs={'class': 'select select-bordered w-full'}),
            )

    def field_groups(self):
        """Yield (vehicle_boundfield, driver_boundfield) pairs for template rendering."""
        i = 1
        while f'vehicle_{i}' in self.fields:
            yield self[f'vehicle_{i}'], self[f'driver_{i}']
            i += 1

    def assignment_pairs(self):
        """Yield (vehicle, driver) model instances from cleaned_data."""
        i = 1
        while f'vehicle_{i}' in self.cleaned_data:
            yield self.cleaned_data[f'vehicle_{i}'], self.cleaned_data[f'driver_{i}']
            i += 1


class CoordinationAcknowledgmentForm(forms.Form):
    acknowledged = forms.BooleanField(
        required=True,
        label='I have read the coordination note and still need a separate vehicle.',
        error_messages={'required': 'You must acknowledge the coordination opportunity before submitting.'},
    )
    coordination_note = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        label='Reason for separate vehicle (optional)',
        help_text='Briefly explain why coordination is not possible for this trip.',
    )
