"""
Fleet Management Forms

Django forms for creating and editing fleet objects.
"""

from django import forms
from django.utils import timezone
from django.core.exceptions import ValidationError
from activities.models import Activity
from .models import (
    TransportRequest, TransportRequestStatus, JourneyType,
    Vehicle, Driver, TripAllocation, TripLog, VehicleStatus, DriverStatus,
    TripAllocationStatus
)
from .allocation_engine import AllocationEngine


class TransportRequestForm(forms.ModelForm):
    """
    Form for creating and editing transport requests.
    """

    # Additional fields for better UX
    linked_activity = forms.ModelChoiceField(
        queryset=Activity.objects.all(),
        required=False,
        empty_label="Select an activity (optional)",
        help_text="Link this request to an existing activity"
    )

    journey_type = forms.ChoiceField(
        choices=JourneyType.choices,
        initial=JourneyType.LINKED,
        widget=forms.RadioSelect,
        help_text="Type of transport journey"
    )

    class Meta:
        model = TransportRequest
        fields = [
            'linked_activity', 'activity_name', 'description',
            'pickup_location', 'destination', 'journey_type',
            'departure_datetime', 'return_datetime', 'num_passengers',
            'justification', 'special_requirements'
        ]
        widgets = {
            'departure_datetime': forms.DateTimeInput(
                attrs={'type': 'datetime-local'}
            ),
            'return_datetime': forms.DateTimeInput(
                attrs={'type': 'datetime-local'}
            ),
            'description': forms.Textarea(attrs={'rows': 3}),
            'justification': forms.Textarea(attrs={'rows': 3}),
            'special_requirements': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Filter activities based on user permissions
        if self.user:
            # Users can only link to activities they have access to
            # For now, show all activities - this can be refined based on permissions
            pass

    def clean(self):
        cleaned_data = super().clean()
        departure = cleaned_data.get('departure_datetime')
        return_dt = cleaned_data.get('return_datetime')
        linked_activity = cleaned_data.get('linked_activity')
        activity_name = cleaned_data.get('activity_name')

        # Validate dates
        if departure and departure < timezone.now():
            raise ValidationError("Departure date cannot be in the past")

        if departure and return_dt and return_dt <= departure:
            raise ValidationError("Return date must be after departure date")

        # Validate activity linking
        if linked_activity and activity_name:
            raise ValidationError(
                "Cannot specify both linked activity and custom activity name. "
                "Choose one or the other."
            )

        if not linked_activity and not activity_name:
            raise ValidationError(
                "Either select a linked activity or provide a custom activity name"
            )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Set the requested_by field
        if self.user:
            instance.requested_by = self.user

        # If linked to activity, copy activity name
        if instance.linked_activity and not instance.activity_name:
            instance.activity_name = instance.linked_activity.name

        if commit:
            instance.save()

        return instance


class TransportRequestApprovalForm(forms.ModelForm):
    """
    Form for approving or rejecting transport requests.
    """

    action = forms.ChoiceField(
        choices=[
            ('approve', 'Approve Request'),
            ('reject', 'Reject Request')
        ],
        widget=forms.RadioSelect,
        help_text="Select the action to take on this request"
    )

    class Meta:
        model = TransportRequest
        fields = ['rejection_reason']
        widgets = {
            'rejection_reason': forms.Textarea(
                attrs={'rows': 3, 'placeholder': 'Reason for rejection (required if rejecting)'}
            )
        }

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        rejection_reason = cleaned_data.get('rejection_reason')

        if action == 'reject' and not rejection_reason:
            raise ValidationError("Rejection reason is required when rejecting a request")

        return cleaned_data


class TripAllocationForm(forms.ModelForm):
    """
    Form for allocating vehicles and drivers to approved requests.
    Includes advanced filtering options.
    """

    # Advanced filtering options
    vehicle_type = forms.ChoiceField(
        choices=[('', 'Any Type')] + list(Vehicle.VEHICLE_TYPES),
        required=False,
        help_text="Filter vehicles by type"
    )
    fuel_type = forms.ChoiceField(
        choices=[('', 'Any Fuel')] + list(Vehicle.FUEL_TYPES),
        required=False,
        help_text="Filter vehicles by fuel type"
    )
    min_capacity = forms.IntegerField(
        min_value=1,
        required=False,
        help_text="Minimum passenger capacity required"
    )
    preferred_location = forms.CharField(
        max_length=100,
        required=False,
        help_text="Preferred location for vehicle/driver"
    )

    class Meta:
        model = TripAllocation
        fields = ['vehicle', 'driver', 'allocation_notes']
        widgets = {
            'allocation_notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.transport_request = kwargs.pop('transport_request', None)
        super().__init__(*args, **kwargs)

        # Use optimized allocation engine with filters
        if self.transport_request:
            # Get filter values
            vehicle_type = self.data.get('vehicle_type') if self.is_bound else None
            min_capacity = self.data.get('min_capacity') if self.is_bound else None
            preferred_location = self.data.get('preferred_location') if self.is_bound else None

            # Get available vehicles using optimized engine with filters
            available_vehicles = AllocationEngine.get_available_vehicles(
                self.transport_request.departure_datetime,
                self.transport_request.return_datetime,
                vehicle_type=vehicle_type,
                min_capacity=min_capacity
            )

            # Get available drivers using optimized engine with filters
            available_drivers = AllocationEngine.get_available_drivers(
                self.transport_request.departure_datetime,
                self.transport_request.return_datetime,
                location=preferred_location
            )

            self.fields['vehicle'].queryset = available_vehicles
            self.fields['driver'].queryset = available_drivers

    def save(self, commit=True):
        instance = super().save(commit=False)

        if self.transport_request:
            instance.transport_request = self.transport_request

        if commit:
            instance.save()

        return instance


class TripCompletionForm(forms.ModelForm):
    """
    Form for completing a trip with odometer and incident details.
    """

    end_mileage = forms.IntegerField(
        min_value=1,
        required=True,
        help_text="Odometer reading at trip completion"
    )
    incident_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                'rows': 3,
                'placeholder': 'Optional incidents, delays, or observations...'
            }
        )
    )

    class Meta:
        model = TripAllocation
        fields = ['actual_distance_km']
        widgets = {
            'actual_distance_km': forms.NumberInput(
                attrs={
                    'step': '0.01',
                    'min': '0.01',
                    'placeholder': 'Enter distance in km'
                }
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['actual_distance_km'].required = False
        self.fields['actual_distance_km'].help_text = "Optional: override auto-calculated distance"

    def clean(self):
        cleaned_data = super().clean()
        end_mileage = cleaned_data.get('end_mileage')

        trip_log = getattr(self.instance, 'trip_log', None)
        if not trip_log:
            raise ValidationError("Trip log was not found. Start the trip first before completing it.")

        if end_mileage is not None and end_mileage <= trip_log.start_mileage:
            raise ValidationError("End mileage must be greater than start mileage")

        if end_mileage is not None and not cleaned_data.get('actual_distance_km'):
            cleaned_data['actual_distance_km'] = end_mileage - trip_log.start_mileage

        return cleaned_data


class TripStartForm(forms.Form):
    """
    Form for starting a trip with initial odometer capture.
    """

    start_mileage = forms.IntegerField(
        min_value=1,
        required=True,
        help_text="Current odometer reading before departure"
    )


class TripCancellationForm(forms.Form):
    """
    Form for cancelling a trip with reason.
    """

    cancellation_reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': 'Please provide a reason for cancellation...'
        }),
        required=True,
        help_text="Reason for cancelling this trip"
    )
