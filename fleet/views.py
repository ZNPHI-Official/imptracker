import csv
import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import ExpressionWrapper, F, IntegerField
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.mixins import GroupRequiredMixin, SortableListMixin
from bookings.models import TripAssignment
from .forms import DriverEditForm, FuelRecordForm, MaintenanceRecordForm, VehicleEditForm
from .models import Driver, FuelRecord, MaintenanceRecord, Vehicle

VIEWER_GROUPS = ['Fleet Manager', 'Dashboard Viewer', 'Superadmin']
MANAGER_GROUPS = ['Fleet Manager', 'Superadmin']


def _is_manager(user):
    return user.groups.filter(name__in=MANAGER_GROUPS).exists() or user.is_superuser


# ---------------------------------------------------------------------------
# Vehicle views
# ---------------------------------------------------------------------------

class VehicleListView(SortableListMixin, GroupRequiredMixin, ListView):
    group_required = VIEWER_GROUPS
    model = Vehicle
    template_name = 'fleet/vehicle_list.html'
    context_object_name = 'vehicles'
    sortable_fields = {
        'plate': 'license_plate',
        'type': 'vehicle_type',
        'mileage': 'current_mileage',
        # km_to_service is an annotation (see get_queryset), not a stored field.
        'service': 'km_to_service',
        'status': 'status',
    }
    default_sort = 'plate'

    def get_queryset(self):
        # Annotate km-to-service so the column can be sorted in the database.
        # Mirrors Vehicle.km_until_service; NULL (no baseline) sorts last under Postgres.
        qs = Vehicle.objects.annotate(
            km_to_service=ExpressionWrapper(
                F('last_service_mileage') + F('maintenance_interval_km') - F('current_mileage'),
                output_field=IntegerField(),
            )
        )
        return self.apply_sort(qs)

    def get(self, request, *args, **kwargs):
        if request.GET.get('export') == 'csv':
            return self._csv_response()
        return super().get(request, *args, **kwargs)

    def _csv_response(self):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="vehicles.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'License Plate', 'Make', 'Model', 'Year', 'Type', 'Fuel', 'Seats',
            'Status', 'Current Mileage (km)', 'Last Service Date',
            'Last Service Mileage (km)', 'Service Interval (km)',
            'Maintenance Status', 'Km to Next Service',
        ])
        for v in Vehicle.objects.order_by('license_plate'):
            writer.writerow([
                v.license_plate, v.make, v.model, v.year,
                v.vehicle_type, v.fuel_type, v.seating_capacity,
                v.status, v.current_mileage,
                v.last_service_date or '',
                v.last_service_mileage or '',
                v.maintenance_interval_km,
                v.maintenance_status,
                v.km_until_service if v.km_until_service is not None else '',
            ])
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = Vehicle.objects.all()
        context['total'] = qs.count()
        context['count_available'] = qs.filter(status='Available').count()
        context['count_on_trip'] = qs.filter(status='On Trip').count()
        context['count_maintenance'] = qs.filter(status='In Maintenance').count()
        context['count_standby'] = qs.filter(status='Emergency Standby').count()
        context['can_edit'] = _is_manager(self.request.user)
        return context


class VehicleDetailView(GroupRequiredMixin, DetailView):
    group_required = VIEWER_GROUPS
    model = Vehicle
    template_name = 'fleet/vehicle_detail.html'
    context_object_name = 'vehicle'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehicle = self.object
        context['fuel_records'] = vehicle.fuel_records.all()
        context['maintenance_records'] = vehicle.maintenance_records.all()
        context['upcoming_trips'] = (
            TripAssignment.objects
            .filter(
                vehicle=vehicle,
                transport_request__period_from__gte=datetime.date.today(),
                transport_request__status__in=['Approved', 'In Progress'],
            )
            .select_related(
                'transport_request__district',
                'transport_request__province',
                'transport_request__department',
            )
            .order_by('transport_request__period_from')
        )
        context['fuel_form'] = FuelRecordForm(initial={'date': datetime.date.today()})
        context['maintenance_form'] = MaintenanceRecordForm(initial={'date': datetime.date.today()})
        context['can_edit'] = _is_manager(self.request.user)
        return context


class VehicleCreateView(GroupRequiredMixin, CreateView):
    group_required = MANAGER_GROUPS
    model = Vehicle
    form_class = VehicleEditForm
    template_name = 'fleet/vehicle_add.html'

    def get_success_url(self):
        messages.success(self.request, 'Vehicle added successfully.')
        return reverse('fleet:vehicle_detail', kwargs={'pk': self.object.pk})


class VehicleEditView(GroupRequiredMixin, UpdateView):
    group_required = MANAGER_GROUPS
    model = Vehicle
    form_class = VehicleEditForm
    template_name = 'fleet/vehicle_edit.html'

    def get_success_url(self):
        messages.success(self.request, 'Vehicle updated successfully.')
        return reverse('fleet:vehicle_detail', kwargs={'pk': self.object.pk})


def _detail_context(vehicle, request, fuel_form=None, maintenance_form=None, active_section=None):
    """Build the full context dict for re-rendering the vehicle detail template on form error."""
    return {
        'vehicle': vehicle,
        'fuel_records': vehicle.fuel_records.all(),
        'maintenance_records': vehicle.maintenance_records.all(),
        'upcoming_trips': (
            TripAssignment.objects
            .filter(
                vehicle=vehicle,
                transport_request__period_from__gte=datetime.date.today(),
                transport_request__status__in=['Approved', 'In Progress'],
            )
            .select_related(
                'transport_request__district',
                'transport_request__province',
                'transport_request__department',
            )
            .order_by('transport_request__period_from')
        ),
        'fuel_form': fuel_form or FuelRecordForm(initial={'date': datetime.date.today()}),
        'maintenance_form': maintenance_form or MaintenanceRecordForm(initial={'date': datetime.date.today()}),
        'can_edit': _is_manager(request.user),
        'active_section': active_section,
    }


def fuel_record_add(request, pk):
    """Add a fuel record to a vehicle. Fleet Manager / Superadmin only."""
    if not request.user.is_authenticated:
        return redirect(f'{reverse_lazy("accounts:login")}?next={request.path}')
    if not _is_manager(request.user):
        raise PermissionDenied

    vehicle = get_object_or_404(Vehicle, pk=pk)

    if request.method == 'POST':
        form = FuelRecordForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.vehicle = vehicle
            record.save()
            messages.success(request, 'Fuel record added.')
            return redirect('fleet:vehicle_detail', pk=vehicle.pk)
        # Invalid: re-render detail page with errors visible in the fuel section.
        return render(request, 'fleet/vehicle_detail.html',
                      _detail_context(vehicle, request, fuel_form=form, active_section='fuel'))

    return redirect('fleet:vehicle_detail', pk=vehicle.pk)


def maintenance_record_add(request, pk):
    """Add a maintenance record. Signal resets the vehicle service baseline.

    If the vehicle was 'In Maintenance', logging a completed service automatically
    returns it to 'Available' — the record itself is the completion signal.
    """
    if not request.user.is_authenticated:
        return redirect(f'{reverse_lazy("accounts:login")}?next={request.path}')
    if not _is_manager(request.user):
        raise PermissionDenied

    vehicle = get_object_or_404(Vehicle, pk=pk)

    if request.method == 'POST':
        form = MaintenanceRecordForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.vehicle = vehicle
            record.save()  # Signal updates last_service_date / last_service_mileage.

            if vehicle.status == 'In Maintenance':
                vehicle.status = 'Available'
                vehicle.save(update_fields=['status', 'updated_at'])

            messages.success(request, 'Maintenance record logged. Baseline updated.')
            return redirect('fleet:vehicle_detail', pk=vehicle.pk)

        return render(request, 'fleet/vehicle_detail.html',
                      _detail_context(vehicle, request, maintenance_form=form, active_section='maintenance'))

    return redirect('fleet:vehicle_detail', pk=vehicle.pk)


# ---------------------------------------------------------------------------
# Driver views
# ---------------------------------------------------------------------------

class DriverListView(SortableListMixin, GroupRequiredMixin, ListView):
    group_required = VIEWER_GROUPS
    model = Driver
    template_name = 'fleet/driver_list.html'
    context_object_name = 'drivers'
    sortable_fields = {'name': 'name', 'phone': 'phone', 'status': 'status'}
    default_sort = 'name'

    def get_queryset(self):
        return self.apply_sort(Driver.objects.all())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = Driver.objects.all()
        context['total'] = qs.count()
        context['count_available'] = qs.filter(status='Available').count()
        context['count_on_assignment'] = qs.filter(status='On Assignment').count()
        context['count_on_leave'] = qs.filter(status='On Leave').count()
        context['can_edit'] = _is_manager(self.request.user)
        return context


class DriverCreateView(GroupRequiredMixin, CreateView):
    group_required = MANAGER_GROUPS
    model = Driver
    form_class = DriverEditForm
    template_name = 'fleet/driver_add.html'
    success_url = reverse_lazy('fleet:driver_list')

    def form_valid(self, form):
        messages.success(self.request, 'Driver added successfully.')
        return super().form_valid(form)


class DriverEditView(GroupRequiredMixin, UpdateView):
    group_required = MANAGER_GROUPS
    model = Driver
    form_class = DriverEditForm
    template_name = 'fleet/driver_edit.html'
    success_url = reverse_lazy('fleet:driver_list')

    def form_valid(self, form):
        messages.success(self.request, 'Driver updated successfully.')
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------

def fuel_records_export(request, pk):
    """Export all fuel records for a vehicle as CSV. All viewer roles allowed."""
    if not request.user.is_authenticated:
        return redirect(f'{reverse_lazy("accounts:login")}?next={request.path}')
    if not request.user.groups.filter(name__in=VIEWER_GROUPS).exists():
        raise PermissionDenied

    vehicle = get_object_or_404(Vehicle, pk=pk)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="fuel_{vehicle.license_plate.replace(" ", "_")}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(['Date', 'Location', 'Litres', 'Cost per Litre (K)', 'Total Cost (K)', 'Mileage at Fill-up (km)', 'Notes'])
    for r in vehicle.fuel_records.order_by('date'):
        writer.writerow([r.date, r.location, r.liters, r.cost_per_liter, r.total_cost, r.mileage_at_fillup, r.notes])
    return response


def maintenance_records_export(request, pk):
    """Export all maintenance records for a vehicle as CSV. All viewer roles allowed."""
    if not request.user.is_authenticated:
        return redirect(f'{reverse_lazy("accounts:login")}?next={request.path}')
    if not request.user.groups.filter(name__in=VIEWER_GROUPS).exists():
        raise PermissionDenied

    vehicle = get_object_or_404(Vehicle, pk=pk)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="maintenance_{vehicle.license_plate.replace(" ", "_")}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(['Date', 'Mileage at Service (km)', 'Service Type', 'Cost (K)', 'Vendor', 'Notes'])
    for r in vehicle.maintenance_records.order_by('date'):
        writer.writerow([r.date, r.mileage_at_service, r.service_type, r.cost, r.vendor, r.notes])
    return response
