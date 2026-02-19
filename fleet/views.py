"""
Fleet Management Views

Class-based views for fleet operations with permission checks.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse_lazy, reverse
from django.db import transaction
from django.http import Http404
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import (
    TransportRequest, TransportRequestStatus, TripAllocation, TripLog,
    TripAllocationStatus, Vehicle, Driver, VehicleStatus, DriverStatus
)
from .forms import (
    TransportRequestForm,
    TransportRequestApprovalForm,
    TripAllocationForm,
    TripStartForm,
    TripCompletionForm,
    TripCancellationForm,
)
from .permissions import (
    fleet_permission_required, FleetPermissionMixin,
    driver_only_required, transport_officer_only_required,
)


# ============================================================================
# TRANSPORT REQUEST VIEWS
# ============================================================================

@method_decorator(login_required, name='dispatch')
class TransportRequestListView(FleetPermissionMixin, ListView):
    """
    List view for transport requests with role-based filtering.
    """
    model = TransportRequest
    template_name = 'fleet/request_list.html'
    context_object_name = 'requests'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user

        # Filter based on user permissions
        if user.has_perm('fleet.view_all_requests'):
            # Transport officers can see all requests
            queryset = TransportRequest.objects.all()
        else:
            # Regular users can only see their own requests
            queryset = TransportRequest.objects.filter(requested_by=user)

        # Apply status filter if provided
        status_filter = self.request.GET.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_choices'] = TransportRequestStatus.choices
        context['current_status'] = self.request.GET.get('status')
        return context


@method_decorator(login_required, name='dispatch')
class TransportRequestDetailView(FleetPermissionMixin, DetailView):
    """
    Detail view for transport requests.
    """
    model = TransportRequest
    template_name = 'fleet/request_detail.html'
    context_object_name = 'request'

    def get_queryset(self):
        user = self.request.user

        if user.has_perm('fleet.view_all_requests'):
            return TransportRequest.objects.all()
        else:
            return TransportRequest.objects.filter(requested_by=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transport_request = self.object

        # Check if user can approve/reject
        context['can_approve'] = (
            self.request.user.has_perm('fleet.approve_request') and
            transport_request.status == TransportRequestStatus.PENDING_APPROVAL
        )

        # Check if user can allocate
        context['can_allocate'] = (
            self.request.user.has_perm('fleet.add_tripallocation') and
            transport_request.status == TransportRequestStatus.APPROVED and
            not hasattr(transport_request, 'trip_allocation')
        )

        # Get allocation if it exists
        try:
            context['allocation'] = transport_request.trip_allocation
        except TripAllocation.DoesNotExist:
            context['allocation'] = None

        return context


@method_decorator(login_required, name='dispatch')
class TransportRequestCreateView(FleetPermissionMixin, CreateView):
    """
    Create view for transport requests.
    """
    model = TransportRequest
    form_class = TransportRequestForm
    template_name = 'fleet/request_form.html'
    success_url = reverse_lazy('fleet:request_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        # Set the requested_by field
        form.instance.requested_by = self.request.user

        # Set initial status
        form.instance.status = TransportRequestStatus.DRAFT

        response = super().form_valid(form)

        messages.success(
            self.request,
            f'Transport request "{self.object.request_id}" created successfully.'
        )

        return response


@method_decorator(login_required, name='dispatch')
class TransportRequestUpdateView(FleetPermissionMixin, UpdateView):
    """
    Update view for transport requests (only for draft/pending requests).
    """
    model = TransportRequest
    form_class = TransportRequestForm
    template_name = 'fleet/request_form.html'

    def get_queryset(self):
        user = self.request.user

        if user.has_perm('fleet.view_all_requests'):
            return TransportRequest.objects.filter(
                status__in=[
                    TransportRequestStatus.DRAFT,
                    TransportRequestStatus.PENDING_APPROVAL
                ]
            )
        else:
            return TransportRequest.objects.filter(
                requested_by=user,
                status__in=[
                    TransportRequestStatus.DRAFT,
                    TransportRequestStatus.PENDING_APPROVAL
                ]
            )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse('fleet:request_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            f'Transport request "{self.object.request_id}" updated successfully.'
        )

        return response


@login_required
@fleet_permission_required('fleet.edit_own_requests')
def submit_request(request, pk):
    """
    Submit a draft request for approval.
    """
    transport_request = get_object_or_404(
        TransportRequest,
        pk=pk,
        requested_by=request.user,
        status=TransportRequestStatus.DRAFT
    )

    if request.method == 'POST':
        transport_request.status = TransportRequestStatus.PENDING_APPROVAL
        transport_request.save()

        # Send notification to transport officers
        from services.fleet_notifications import send_transport_request_submitted_notification
        send_transport_request_submitted_notification(transport_request)

        messages.success(
            request,
            f'Request "{transport_request.request_id}" submitted for approval.'
        )

        return redirect('fleet:request_detail', pk=pk)

    return render(request, 'fleet/request_confirm_submit.html', {
        'request': transport_request
    })


@login_required
@transport_officer_only_required
def approve_request(request, pk):
    """
    Approve or reject a transport request.
    """
    transport_request = get_object_or_404(
        TransportRequest,
        pk=pk,
        status=TransportRequestStatus.PENDING_APPROVAL
    )

    if request.method == 'POST':
        form = TransportRequestApprovalForm(request.POST, instance=transport_request)

        if form.is_valid():
            action = form.cleaned_data['action']

            if action == 'approve':
                transport_request.status = TransportRequestStatus.APPROVED
                transport_request.approved_by = request.user
                transport_request.save()

                # Send approval notification
                from services.fleet_notifications import send_transport_request_approved_notification
                send_transport_request_approved_notification(transport_request, approved_by=request.user)

                messages.success(
                    request,
                    f'Request "{transport_request.request_id}" approved successfully.'
                )

            elif action == 'reject':
                transport_request.status = TransportRequestStatus.REJECTED
                transport_request.rejection_reason = form.cleaned_data['rejection_reason']
                transport_request.save()

                # Send rejection notification
                from services.fleet_notifications import send_transport_request_rejected_notification
                send_transport_request_rejected_notification(
                    transport_request,
                    rejected_by=request.user,
                    rejection_reason=form.cleaned_data['rejection_reason']
                )

                messages.success(
                    request,
                    f'Request "{transport_request.request_id}" rejected.'
                )

            return redirect('fleet:request_detail', pk=pk)

    else:
        form = TransportRequestApprovalForm(instance=transport_request)

    return render(request, 'fleet/request_approve.html', {
        'request': transport_request,
        'form': form
    })


# ============================================================================
# TRIP ALLOCATION VIEWS
# ============================================================================

@login_required
@transport_officer_only_required
def allocate_trip(request, pk):
    """
    Allocate vehicle and driver to an approved request.
    """
    transport_request = get_object_or_404(
        TransportRequest,
        pk=pk,
        status=TransportRequestStatus.APPROVED
    )

    # Check if already allocated
    if hasattr(transport_request, 'trip_allocation'):
        messages.error(request, 'This request is already allocated.')
        return redirect('fleet:request_detail', pk=pk)

    if request.method == 'POST':
        # Check if this is a filter application or allocation submission
        if 'apply_filters' in request.POST:
            # Just re-render the form with filters applied
            form = TripAllocationForm(request.POST, transport_request=transport_request)
        else:
            # Process allocation
            form = TripAllocationForm(request.POST, transport_request=transport_request)

            if form.is_valid():
                allocation = form.save()

                # Update request status
                transport_request.status = TransportRequestStatus.ALLOCATED
                transport_request.save()

                # Send allocation notification
                from services.fleet_notifications import send_trip_allocated_notification
                send_trip_allocated_notification(allocation, allocated_by=request.user)

                messages.success(
                    request,
                    f'Trip allocated successfully. Vehicle: {allocation.vehicle.registration_number}, '
                    f'Driver: {allocation.driver.user.get_full_name()}'
                )

                return redirect('fleet:request_detail', pk=pk)

    else:
        form = TripAllocationForm(transport_request=transport_request)

    return render(request, 'fleet/request_allocate.html', {
        'request': transport_request,
        'form': form
    })


@login_required
@driver_only_required
def confirm_allocation(request, pk):
    """
    Driver confirms trip allocation.
    """
    allocation = get_object_or_404(
        TripAllocation,
        pk=pk,
        driver__user=request.user,
        status=TripAllocationStatus.ALLOCATED
    )

    if request.method == 'POST':
        allocation.status = TripAllocationStatus.CONFIRMED
        allocation.confirmed_by = request.user
        allocation.confirmed_at = timezone.now()
        allocation.save()

        # Send confirmation notification
        from services.fleet_notifications import send_trip_confirmed_notification
        send_trip_confirmed_notification(allocation, confirmed_by=request.user)

        messages.success(
            request,
            f'Trip "{allocation.transport_request.request_id}" confirmed successfully.'
        )

        return redirect('fleet:request_detail', pk=allocation.transport_request.pk)

    return render(request, 'fleet/allocation_confirm.html', {
        'allocation': allocation
    })


@login_required
@driver_only_required
def start_trip(request, pk):
    """
    Driver starts the trip.
    """
    allocation = get_object_or_404(
        TripAllocation,
        pk=pk,
        driver__user=request.user,
        status=TripAllocationStatus.CONFIRMED
    )

    if request.method == 'POST':
        form = TripStartForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                allocation.status = TripAllocationStatus.IN_PROGRESS
                allocation.actual_departure_datetime = timezone.now()
                allocation.save()

                # Update transport request status
                allocation.transport_request.status = TransportRequestStatus.IN_PROGRESS
                allocation.transport_request.save()

                # Mark operational statuses while trip is underway
                allocation.vehicle.status = VehicleStatus.BOOKED
                allocation.vehicle.save(update_fields=['status'])
                allocation.driver.status = DriverStatus.ASSIGNED
                allocation.driver.save(update_fields=['status'])

                TripLog.objects.update_or_create(
                    trip_allocation=allocation,
                    defaults={
                        'start_mileage': form.cleaned_data['start_mileage'],
                        'created_by': request.user,
                        'updated_by': request.user,
                    },
                )

            # Send trip started notification
            from services.fleet_notifications import send_trip_started_notification
            send_trip_started_notification(allocation, started_by=request.user)

            messages.success(
                request,
                f'Trip "{allocation.transport_request.request_id}" started successfully.'
            )

            return redirect('fleet:request_detail', pk=allocation.transport_request.pk)
    else:
        form = TripStartForm()

    return render(request, 'fleet/trip_start.html', {
        'allocation': allocation,
        'form': form,
    })


@login_required
@driver_only_required
def complete_trip(request, pk):
    """
    Driver completes the trip.
    """
    allocation = get_object_or_404(
        TripAllocation,
        pk=pk,
        driver__user=request.user,
        status=TripAllocationStatus.IN_PROGRESS
    )

    if request.method == 'POST':
        form = TripCompletionForm(request.POST, instance=allocation)

        if form.is_valid():
            with transaction.atomic():
                allocation = form.save(commit=False)
                allocation.status = TripAllocationStatus.COMPLETED
                allocation.actual_return_datetime = timezone.now()

                trip_log = allocation.trip_log
                trip_log.end_mileage = form.cleaned_data['end_mileage']
                trip_log.incident_notes = form.cleaned_data.get('incident_notes', '')
                trip_log.end_datetime = allocation.actual_return_datetime
                trip_log.updated_by = request.user
                trip_log.save()

                # Keep TripAllocation distance in sync with TripLog
                if trip_log.distance is not None:
                    allocation.actual_distance_km = trip_log.distance

                allocation.save()

                # Update transport request status
                allocation.transport_request.status = TransportRequestStatus.COMPLETED
                allocation.transport_request.save()

                # Restore resource availability
                allocation.vehicle.status = VehicleStatus.AVAILABLE
                allocation.vehicle.save(update_fields=['status'])
                allocation.driver.status = DriverStatus.AVAILABLE
                allocation.driver.save(update_fields=['status'])

            # Send trip completed notification
            from services.fleet_notifications import send_trip_completed_notification
            send_trip_completed_notification(allocation, completed_by=request.user)

            messages.success(
                request,
                f'Trip "{allocation.transport_request.request_id}" completed successfully.'
            )

            return redirect('fleet:request_detail', pk=allocation.transport_request.pk)

    else:
        form = TripCompletionForm(instance=allocation)

    return render(request, 'fleet/trip_complete.html', {
        'allocation': allocation,
        'form': form
    })


@login_required
@transport_officer_only_required
def cancel_trip(request, pk):
    """
    Cancel a trip allocation.
    """
    allocation = get_object_or_404(
        TripAllocation,
        pk=pk,
        status__in=[
            TripAllocationStatus.ALLOCATED,
            TripAllocationStatus.CONFIRMED,
            TripAllocationStatus.IN_PROGRESS
        ]
    )

    if request.method == 'POST':
        form = TripCancellationForm(request.POST)

        if form.is_valid():
            cancellation_reason = form.cleaned_data['cancellation_reason']

            with transaction.atomic():
                # Update allocation status
                allocation.status = TripAllocationStatus.CANCELLED
                allocation.save()

                # Update transport request status
                allocation.transport_request.status = TransportRequestStatus.CANCELLED
                allocation.transport_request.save()

                # Restore resource availability
                allocation.vehicle.status = VehicleStatus.AVAILABLE
                allocation.vehicle.save(update_fields=['status'])
                allocation.driver.status = DriverStatus.AVAILABLE
                allocation.driver.save(update_fields=['status'])

                if hasattr(allocation, 'trip_log'):
                    allocation.trip_log.incident_notes = cancellation_reason
                    allocation.trip_log.updated_by = request.user
                    allocation.trip_log.save(update_fields=['incident_notes', 'updated_by', 'updated_at'])

            # Send trip cancelled notification
            from services.fleet_notifications import send_trip_cancelled_notification
            send_trip_cancelled_notification(
                allocation,
                cancelled_by=request.user,
                cancellation_reason=cancellation_reason
            )

            messages.success(
                request,
                f'Trip "{allocation.transport_request.request_id}" cancelled successfully.'
            )

            return redirect('fleet:request_detail', pk=allocation.transport_request.pk)

    else:
        form = TripCancellationForm()

    return render(request, 'fleet/trip_cancel.html', {
        'allocation': allocation,
        'form': form
    })


# ============================================================================
# DASHBOARD VIEWS
# ============================================================================

class FleetDashboardView(LoginRequiredMixin, FleetPermissionMixin, ListView):
    """
    Fleet management dashboard showing overview of requests, allocations, etc.
    """
    template_name = 'fleet/dashboard.html'
    context_object_name = 'recent_requests'

    def get_queryset(self):
        user = self.request.user

        if user.has_perm('fleet.view_all_requests'):
            return TransportRequest.objects.all()[:10]
        else:
            return TransportRequest.objects.filter(requested_by=user)[:10]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Get counts based on permissions
        if user.has_perm('fleet.view_all_requests'):
            context['pending_count'] = TransportRequest.objects.filter(
                status=TransportRequestStatus.PENDING_APPROVAL
            ).count()

            context['approved_count'] = TransportRequest.objects.filter(
                status=TransportRequestStatus.APPROVED
            ).count()

            context['allocated_count'] = TransportRequest.objects.filter(
                status=TransportRequestStatus.ALLOCATED
            ).count()

        else:
            context['pending_count'] = TransportRequest.objects.filter(
                requested_by=user,
                status=TransportRequestStatus.PENDING_APPROVAL
            ).count()

            context['approved_count'] = TransportRequest.objects.filter(
                requested_by=user,
                status=TransportRequestStatus.APPROVED
            ).count()

            context['allocated_count'] = TransportRequest.objects.filter(
                requested_by=user,
                status=TransportRequestStatus.ALLOCATED
            ).count()

        # Vehicle and driver counts (for officers)
        if user.has_perm('fleet.manage_vehicle'):
            context['available_vehicles'] = Vehicle.objects.filter(
                status=VehicleStatus.AVAILABLE
            ).count()

            context['available_drivers'] = Driver.objects.filter(
                status=DriverStatus.AVAILABLE
            ).count()

        return context
