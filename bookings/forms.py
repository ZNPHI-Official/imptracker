from django import forms

from fleet.models import Driver, Vehicle
from .models import Department, District, TransportRequest

ADHOC_CHOICE = 'adhoc'


def assigned_activities(user):
    """Implementation Tracker activities the user is responsible for."""
    from activities.models import Activity
    if user is None or not user.is_authenticated:
        return Activity.objects.none()
    return (
        Activity.objects
        .filter(responsible_officer=user, deleted=False, retired=False)
        .order_by('-year', 'activity_id')
    )


class TransportRequestForm(forms.ModelForm):
    """Transport request form. Requester name, position and department are not
    entered by the user — they come from the logged-in account. The programme
    activity is picked from the user's assigned tracker activities, or entered
    as free text for adhoc trips."""

    activity_choice = forms.ChoiceField(label='Programme / Activity')
    # ZNPHI uses "cluster", "unit" and "department" interchangeably; the fleet
    # side stores a Department row mapped from the tracker Cluster on save.
    cluster_choice = forms.ChoiceField(label='Cluster/Unit/Department')
    adhoc_activity = forms.CharField(
        label='Adhoc activity description',
        max_length=300,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Describe the activity for this trip'}),
    )

    class Meta:
        model = TransportRequest
        fields = [
            'period_from', 'period_to', 'province', 'district',
            'destination', 'num_vehicles', 'num_drivers', 'num_passengers',
            'is_emergency',
        ]
        widgets = {
            'period_from': forms.DateInput(attrs={'type': 'date'}),
            'period_to': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.user_clusters = (
            list(user.clusters.all()) if user is not None and user.is_authenticated else []
        )
        self.fields['cluster_choice'].choices = [
            (str(c.pk), f'{c.full_name} ({c.short_name})') for c in self.user_clusters
        ]
        if len(self.user_clusters) == 1:
            self.fields['cluster_choice'].initial = str(self.user_clusters[0].pk)
        # With no clusters the friendly non-field error from clean() suffices.
        self.fields['cluster_choice'].required = bool(self.user_clusters)
        self.activities = list(assigned_activities(user))
        self.fields['activity_choice'].choices = (
            [('', 'Select activity…')]
            + [(str(a.pk), f'{a.activity_id} — {a.name}') for a in self.activities]
            + [(ADHOC_CHOICE, 'Adhoc (activity not in the tracker)')]
        )
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

    def clean_activity_choice(self):
        choice = self.cleaned_data['activity_choice']
        if choice == ADHOC_CHOICE:
            return choice
        if not any(str(a.pk) == choice for a in self.activities):
            raise forms.ValidationError('Select one of your assigned activities or Adhoc.')
        return choice

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

        # Requester details come from the account, not the form. The selected
        # tracker Cluster is mapped to the fleet Department table by name.
        if self.user is not None:
            if not self.user_clusters:
                raise forms.ValidationError(
                    'Your account has no cluster/unit/department assigned. Please ask a '
                    'system administrator to assign your cluster before requesting transport.'
                )
            cleaned['requester_name'] = self.user.get_full_name() or self.user.username
            cleaned['position'] = self.user.position
            choice = cleaned.get('cluster_choice')
            cluster = next((c for c in self.user_clusters if str(c.pk) == choice), None)
            if cluster is None:
                self.add_error('cluster_choice', 'Select one of your assigned clusters.')
            else:
                cleaned['department'] = Department.objects.get_or_create(
                    name=cluster.full_name[:200]
                )[0]

        # Resolve the selected activity into the stored fields.
        choice = cleaned.get('activity_choice')
        if choice == ADHOC_CHOICE:
            adhoc = (cleaned.get('adhoc_activity') or '').strip()
            if not adhoc:
                self.add_error('adhoc_activity', 'Describe the adhoc activity for this trip.')
            cleaned['activity'] = None
            cleaned['programme_activity'] = adhoc
        elif choice:
            activity = next(a for a in self.activities if str(a.pk) == choice)
            cleaned['activity'] = activity
            cleaned['programme_activity'] = f'{activity.activity_id} — {activity.name}'[:300]
        return cleaned


class RequestApprovalForm(forms.Form):
    admin_comment = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
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
                widget=forms.Select(attrs={'class': 'form-select'}),
            )
            self.fields[f'driver_{i}'] = forms.ModelChoiceField(
                queryset=driver_qs,
                label=f'Driver {i}',
                empty_label='Select driver…',
                widget=forms.Select(attrs={'class': 'form-select'}),
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
