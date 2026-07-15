from django import forms

from .models import Driver, FuelRecord, MaintenanceRecord, Vehicle

_input = 'input input-bordered w-full'
_select = 'select select-bordered w-full'
_textarea = 'textarea textarea-bordered w-full'


class VehicleEditForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = [
            'make', 'model', 'year', 'license_plate', 'vehicle_type',
            'current_mileage', 'seating_capacity', 'fuel_type', 'status',
            'maintenance_interval_km',
        ]
        widgets = {
            'make': forms.TextInput(attrs={'class': _input}),
            'model': forms.TextInput(attrs={'class': _input}),
            'year': forms.NumberInput(attrs={'class': _input, 'min': 1990, 'max': 2035}),
            'license_plate': forms.TextInput(attrs={'class': _input}),
            'vehicle_type': forms.Select(attrs={'class': _select}),
            'current_mileage': forms.NumberInput(attrs={'class': _input, 'min': 0}),
            'seating_capacity': forms.NumberInput(attrs={'class': _input, 'min': 1, 'max': 50}),
            'fuel_type': forms.Select(attrs={'class': _select}),
            'status': forms.Select(attrs={'class': _select}),
            'maintenance_interval_km': forms.NumberInput(attrs={'class': _input, 'min': 500}),
        }


class FuelRecordForm(forms.ModelForm):
    class Meta:
        model = FuelRecord
        fields = ['date', 'liters', 'cost_per_liter', 'total_cost', 'location', 'mileage_at_fillup', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'class': _input, 'type': 'date'}),
            'liters': forms.NumberInput(attrs={'class': _input, 'min': 0, 'step': '0.01'}),
            'cost_per_liter': forms.NumberInput(attrs={'class': _input, 'min': 0, 'step': '0.01'}),
            'total_cost': forms.NumberInput(attrs={'class': _input, 'min': 0, 'step': '0.01'}),
            'location': forms.TextInput(attrs={'class': _input}),
            'mileage_at_fillup': forms.NumberInput(attrs={'class': _input, 'min': 0}),
            'notes': forms.Textarea(attrs={'class': _textarea, 'rows': 2}),
        }


class MaintenanceRecordForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRecord
        fields = ['date', 'mileage_at_service', 'service_type', 'cost', 'vendor', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'class': _input, 'type': 'date'}),
            'mileage_at_service': forms.NumberInput(attrs={'class': _input, 'min': 0}),
            'service_type': forms.TextInput(attrs={'class': _input}),
            'cost': forms.NumberInput(attrs={'class': _input, 'min': 0, 'step': '0.01'}),
            'vendor': forms.TextInput(attrs={'class': _input}),
            'notes': forms.Textarea(attrs={'class': _textarea, 'rows': 2}),
        }


class DriverEditForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = ['name', 'phone', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'class': _input}),
            'phone': forms.TextInput(attrs={'class': _input}),
            'status': forms.Select(attrs={'class': _select}),
        }
