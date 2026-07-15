import csv
import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db.models import Case, F, IntegerField, Q, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import DetailView, ListView, View

from accounts.mixins import GroupRequiredMixin
from fleet.models import Driver, Vehicle
from .forms import CoordinationAcknowledgmentForm, RequestApprovalForm, TransportRequestForm
from .models import District, Province, TransportRequest, TripAssignment
from .services import sync_fleet_statuses

# Default nudge window. Made configurable via Settings model in Phase 8.
NUDGE_WINDOW_DAYS = 7

# Default buffer days between consecutive trips for the same vehicle. Made configurable in Phase 8.
BUFFER_DAYS = 1


def _send_new_request_email(transport_request):
    """Send a notification email when a new request is submitted, if enabled in Settings."""
    from settings_app.models import Settings
    site_settings = Settings.load()
    if not site_settings.email_notifications_enabled or not site_settings.notification_email:
        return
    send_mail(
        subject=f'New transport request: {transport_request.programme_activity}',
        message=(
            f'A new transport request has been submitted.\n\n'
            f'Requester: {transport_request.requester_name}\n'
            f'Department: {transport_request.department}\n'
            f'Programme/Activity: {transport_request.programme_activity}\n'
            f'Period: {transport_request.period_from} to {transport_request.period_to}\n'
            f'Destination: {transport_request.destination}, {transport_request.district}, {transport_request.province}\n'
            f'Vehicles requested: {transport_request.num_vehicles}\n'
        ),
        from_email=None,  # uses DEFAULT_FROM_EMAIL from settings
        recipient_list=[site_settings.notification_email],
        fail_silently=True,
    )


def get_overlapping_trips(district, period_from, period_to, nudge_days=NUDGE_WINDOW_DAYS):
    """Return active requests to the same district whose start dates AND end dates
    both fall within `nudge_days` of the requested trip.

    Matching start-to-start and end-to-end (rather than padding the whole period
    and testing for any interval overlap) means trips are flagged only when they
    genuinely run alongside each other. A trip that merely begins right after
    another one ends is no longer flagged as a coordination opportunity.
    """
    start_low = period_from - datetime.timedelta(days=nudge_days)
    start_high = period_from + datetime.timedelta(days=nudge_days)
    end_low = period_to - datetime.timedelta(days=nudge_days)
    end_high = period_to + datetime.timedelta(days=nudge_days)
    return (
        TransportRequest.objects
        .filter(
            district=district,
            status__in=['Submitted', 'Approved', 'In Progress'],
            period_from__gte=start_low,
            period_from__lte=start_high,
            period_to__gte=end_low,
            period_to__lte=end_high,
        )
        .select_related('department')
        .prefetch_related('assignments__vehicle')
    )


def _save_transport_request(cleaned_data, submitted_by=None,
                             coordination_acknowledged=False, coordination_note=''):
    return TransportRequest.objects.create(
        requester_name=cleaned_data['requester_name'],
        department=cleaned_data['department'],
        position=cleaned_data['position'],
        programme_activity=cleaned_data['programme_activity'],
        period_from=cleaned_data['period_from'],
        period_to=cleaned_data['period_to'],
        province=cleaned_data['province'],
        district=cleaned_data['district'],
        destination=cleaned_data['destination'],
        num_vehicles=cleaned_data['num_vehicles'],
        num_drivers=cleaned_data['num_drivers'],
        num_passengers=cleaned_data['num_passengers'],
        is_emergency=cleaned_data.get('is_emergency', False),
        submitted_by=submitted_by,
        coordination_acknowledged=coordination_acknowledged,
        coordination_note=coordination_note,
    )


class DistrictOptionsView(View):
    """HTMX endpoint: returns <option> tags for districts in the selected province."""

    def get(self, request):
        province_id = request.GET.get('province')
        districts = District.objects.none()
        if province_id:
            try:
                districts = District.objects.filter(province_id=int(province_id))
            except (ValueError, TypeError):
                pass
        return render(request, 'bookings/htmx/district_options.html', {'districts': districts})


class TransportRequestCreateView(GroupRequiredMixin, View):
    group_required = ['Requester', 'Fleet Manager', 'Dashboard Viewer', 'Superadmin']
    template_name = 'bookings/request_form.html'

    def get(self, request):
        form = TransportRequestForm()
        provinces = Province.objects.all()
        return render(request, self.template_name, {'form': form, 'provinces': provinces})

    def post(self, request):
        form = TransportRequestForm(request.POST)
        provinces = Province.objects.all()

        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'provinces': provinces})

        from settings_app.models import Settings
        site_settings = Settings.load()

        cd = form.cleaned_data
        is_late = (cd['period_from'] - datetime.date.today()) < datetime.timedelta(weeks=2)
        overlapping = get_overlapping_trips(
            cd['district'], cd['period_from'], cd['period_to'],
            nudge_days=site_settings.nudge_window_days(),
        )

        if overlapping.exists():
            # Store POST data in session; redirect to nudge page.
            request.session['pending_request_data'] = {
                k: v for k, v in request.POST.items() if k != 'csrfmiddlewaretoken'
            }
            request.session['overlapping_trip_ids'] = list(overlapping.values_list('id', flat=True))
            request.session['pending_request_is_late'] = is_late
            return redirect('bookings:coordination_nudge')

        tr = _save_transport_request(cd, submitted_by=request.user)
        _send_new_request_email(tr)
        if is_late:
            messages.warning(
                request,
                'Request submitted. Note: this trip starts in less than 2 weeks — '
                'please allow extra time for the Fleet Manager to process it.'
            )
        else:
            messages.success(request, 'Transport request submitted successfully.')
        return redirect(reverse_lazy('bookings:my_requests'))


class CoordinationNudgeView(LoginRequiredMixin, View):
    """Show coordination overlap details and require the requester to acknowledge
    before the request is saved."""
    template_name = 'bookings/coordination_nudge.html'

    def _recover_session(self, request):
        """Rebuild form and overlapping queryset from session. Returns (raw, form, overlapping)
        or (None, None, None) if session data is missing."""
        raw = request.session.get('pending_request_data')
        if not raw:
            return None, None, None
        form = TransportRequestForm(raw)
        form.is_valid()  # populate cleaned_data without raising on errors
        trip_ids = request.session.get('overlapping_trip_ids', [])
        overlapping = (
            TransportRequest.objects
            .filter(id__in=trip_ids)
            .select_related('department')
            .prefetch_related('assignments__vehicle')
        )
        return raw, form, overlapping

    def get(self, request):
        raw, form, overlapping = self._recover_session(request)
        if raw is None:
            return redirect('bookings:request_create')
        is_late = request.session.get('pending_request_is_late', False)
        return render(request, self.template_name, {
            'form': form,
            'overlapping': overlapping,
            'ack_form': CoordinationAcknowledgmentForm(),
            'is_late': is_late,
        })

    def post(self, request):
        raw, form, overlapping = self._recover_session(request)
        if raw is None:
            return redirect('bookings:request_create')

        ack_form = CoordinationAcknowledgmentForm(request.POST)
        if not ack_form.is_valid():
            is_late = request.session.get('pending_request_is_late', False)
            return render(request, self.template_name, {
                'form': form,
                'overlapping': overlapping,
                'ack_form': ack_form,
                'is_late': is_late,
            })

        tr = _save_transport_request(
            form.cleaned_data,
            submitted_by=request.user,
            coordination_acknowledged=True,
            coordination_note=ack_form.cleaned_data.get('coordination_note', ''),
        )
        _send_new_request_email(tr)

        # Clear session data after saving.
        request.session.pop('pending_request_data', None)
        request.session.pop('overlapping_trip_ids', None)
        request.session.pop('pending_request_is_late', None)

        is_late = request.session.get('pending_request_is_late', False)
        if is_late:
            messages.warning(
                request,
                'Request submitted. Note: this trip starts in less than 2 weeks.'
            )
        else:
            messages.success(request, 'Transport request submitted successfully.')
        return redirect(reverse_lazy('bookings:my_requests'))


class MyRequestsView(GroupRequiredMixin, ListView):
    group_required = ['Requester', 'Fleet Manager', 'Dashboard Viewer', 'Superadmin']
    template_name = 'bookings/my_requests.html'
    context_object_name = 'requests'

    def get_queryset(self):
        return (
            TransportRequest.objects
            .filter(submitted_by=self.request.user)
            .select_related('district', 'province', 'department')
            .prefetch_related('assignments__vehicle')
        )


class TransportRequestDetailView(LoginRequiredMixin, DetailView):
    model = TransportRequest
    template_name = 'bookings/request_detail.html'
    context_object_name = 'transport_request'

    def get_queryset(self):
        user = self.request.user
        # Fleet managers and superadmins can view any request; requesters see only their own.
        if user.groups.filter(name__in=['Fleet Manager', 'Superadmin']).exists() or user.is_superuser:
            return TransportRequest.objects.all()
        return TransportRequest.objects.filter(submitted_by=user)

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj is None:
            raise PermissionDenied
        return obj


class TransportRequestCancelView(LoginRequiredMixin, View):
    """POST-only: cancel a pre-completion transport request."""

    def post(self, request, pk):
        user = request.user
        is_manager = user.groups.filter(name__in=['Fleet Manager', 'Superadmin']).exists() or user.is_superuser
        qs = TransportRequest.objects.all() if is_manager else TransportRequest.objects.filter(submitted_by=user)
        tr = get_object_or_404(qs, pk=pk)

        if tr.status in ('Completed', 'Cancelled'):
            messages.error(request, 'This request cannot be cancelled.')
        else:
            tr.status = 'Cancelled'
            tr.save()
            messages.success(request, 'Request cancelled successfully.')

        return redirect('bookings:my_requests')


# ---------------------------------------------------------------------------
# Phase 4: Fleet Manager approval and assignment workflow
# ---------------------------------------------------------------------------

def get_available_vehicles(period_from, period_to, buffer_days=BUFFER_DAYS, exclude_request_pk=None):
    """Return vehicles that can be assigned for the given date range.

    Excludes vehicles that:
    - Are already committed to a trip whose dates (plus buffer) overlap the window.
    - Have overdue maintenance (current mileage exceeds last_service_mileage + interval).

    When editing an already-approved request, pass `exclude_request_pk` so that
    request's own assignments don't count as a conflict — its currently-assigned
    vehicles stay selectable.
    """
    window_start = period_from - datetime.timedelta(days=buffer_days)
    window_end = period_to + datetime.timedelta(days=buffer_days)

    booked = TripAssignment.objects.filter(
        transport_request__status__in=['Submitted', 'Approved', 'In Progress'],
        transport_request__period_from__lte=window_end,
        transport_request__period_to__gte=window_start,
    )
    if exclude_request_pk:
        booked = booked.exclude(transport_request_id=exclude_request_pk)
    booked_ids = booked.values_list('vehicle_id', flat=True)

    # Overdue: current mileage exceeds the mileage threshold for next service.
    overdue = Q(
        last_service_mileage__isnull=False,
        current_mileage__gt=F('last_service_mileage') + F('maintenance_interval_km'),
    )

    return (
        Vehicle.objects
        .exclude(pk__in=booked_ids)
        .exclude(overdue)
        .order_by('license_plate')
    )


def get_available_drivers(period_from, period_to, buffer_days=BUFFER_DAYS, exclude_request_pk=None):
    """Return drivers with Available status and no overlapping assignment (with buffer).

    When editing an already-approved request, pass `exclude_request_pk` so that
    request's own assignments don't count as a conflict.
    """
    window_start = period_from - datetime.timedelta(days=buffer_days)
    window_end = period_to + datetime.timedelta(days=buffer_days)

    busy = TripAssignment.objects.filter(
        transport_request__status__in=['Submitted', 'Approved', 'In Progress'],
        transport_request__period_from__lte=window_end,
        transport_request__period_to__gte=window_start,
    )
    if exclude_request_pk:
        busy = busy.exclude(transport_request_id=exclude_request_pk)
    busy_ids = busy.values_list('driver_id', flat=True)

    # Drivers already assigned to this request may have status 'On Assignment';
    # include them (alongside Available) so they remain selectable while editing.
    qs = Driver.objects.exclude(pk__in=busy_ids)
    if exclude_request_pk:
        own_driver_ids = (
            TripAssignment.objects
            .filter(transport_request_id=exclude_request_pk)
            .values_list('driver_id', flat=True)
        )
        return qs.filter(Q(status='Available') | Q(pk__in=own_driver_ids))
    return qs.filter(status='Available')


def _vehicles_with_info(available_vehicles_qs):
    """Attach upcoming-trip context to each available vehicle for display on the review screen."""
    result = []
    for v in available_vehicles_qs:
        # Most recent upcoming/active assignment — tells the fleet manager when this vehicle
        # last returns and from where, so they can judge scheduling feasibility.
        upcoming = (
            TripAssignment.objects
            .filter(vehicle=v, transport_request__status__in=['Approved', 'In Progress'])
            .select_related('transport_request__district')
            .order_by('transport_request__period_to')
            .last()
        )
        result.append({
            'vehicle': v,
            'return_trip': upcoming.transport_request if upcoming else None,
        })
    return result


class RequestQueueView(GroupRequiredMixin, ListView):
    """Landing page for Fleet Managers. Shows requests awaiting action: pending
    (Submitted) requests to review, and Approved requests that can still be
    re-assigned before the trip starts. In-progress and completed trips are not
    shown here — they're no longer actionable from the queue."""
    group_required = ['Fleet Manager', 'Superadmin']
    template_name = 'bookings/request_queue.html'
    context_object_name = 'requests'

    # ?show= filter → statuses included. Defaults to all actionable requests.
    SHOW_FILTERS = {
        'pending': ['Submitted'],
        'approved': ['Approved'],
        'all': ['Submitted', 'Approved'],
    }

    def _show(self):
        show = self.request.GET.get('show', 'all')
        return show if show in self.SHOW_FILTERS else 'all'

    def _base_queryset(self, statuses):
        return (
            TransportRequest.objects
            .filter(status__in=statuses)
            .select_related('department', 'district', 'province')
            .prefetch_related('assignments__vehicle', 'assignments__driver')
            # Submitted (need review) before Approved; then emergencies, then start date.
            .annotate(status_rank=Case(
                When(status='Submitted', then=0),
                default=1,
                output_field=IntegerField(),
            ))
            .order_by('status_rank', '-is_emergency', 'period_from')
        )

    def get_queryset(self):
        return self._base_queryset(self.SHOW_FILTERS[self._show()])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_show'] = self._show()
        # Tab counts are independent of the active filter.
        context['count_pending'] = TransportRequest.objects.filter(status='Submitted').count()
        context['count_approved'] = TransportRequest.objects.filter(status='Approved').count()
        return context

    def get(self, request, *args, **kwargs):
        if request.GET.get('export') == 'csv':
            return self._csv_response()
        return super().get(request, *args, **kwargs)

    def _csv_response(self):
        qs = self._base_queryset(self.SHOW_FILTERS[self._show()])
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="request_queue.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Date Submitted', 'Emergency', 'Requester', 'Position',
            'Department', 'Programme / Activity', 'Period From', 'Period To',
            'Province', 'District', 'Destination',
            '# Vehicles', '# Drivers', '# Passengers', 'Status',
        ])
        for tr in qs:
            writer.writerow([
                tr.pk,
                tr.date_of_request,
                'Yes' if tr.is_emergency else 'No',
                tr.requester_name,
                tr.position,
                tr.department.name,
                tr.programme_activity,
                tr.period_from,
                tr.period_to,
                tr.province.name,
                tr.district.name,
                tr.destination,
                tr.num_vehicles,
                tr.num_drivers,
                tr.num_passengers,
                tr.status,
            ])
        return response


class RequestReviewView(GroupRequiredMixin, View):
    """Review a request that's awaiting action. A Submitted request can be approved
    (with vehicle/driver assignment) or rejected. An already-Approved request can be
    re-opened here to change its assignments before the trip starts."""
    group_required = ['Fleet Manager', 'Superadmin']
    template_name = 'bookings/request_review.html'

    # Statuses that may be opened for review/editing from the queue.
    EDITABLE_STATUSES = ['Submitted', 'Approved']

    def _get_tr(self, pk):
        return get_object_or_404(
            TransportRequest.objects
            .select_related('department', 'district', 'province')
            .prefetch_related('assignments'),
            pk=pk,
            status__in=self.EDITABLE_STATUSES,
        )

    def _availability(self, tr, site_settings):
        """Available vehicles/drivers for this request. When editing an already-approved
        request, its own assignments are excluded from the conflict check so the
        currently-assigned vehicles and drivers remain selectable."""
        exclude_pk = tr.pk if tr.status == 'Approved' else None
        avail_v = get_available_vehicles(
            tr.period_from, tr.period_to,
            buffer_days=site_settings.buffer_days, exclude_request_pk=exclude_pk,
        )
        avail_d = get_available_drivers(
            tr.period_from, tr.period_to,
            buffer_days=site_settings.buffer_days, exclude_request_pk=exclude_pk,
        )
        return avail_v, avail_d

    def _initial_from_assignments(self, tr):
        """Pre-fill the form with the request's current assignments (for editing)."""
        initial = {'admin_comment': tr.admin_comment}
        for i, a in enumerate(tr.assignments.all(), start=1):
            initial[f'vehicle_{i}'] = a.vehicle_id
            initial[f'driver_{i}'] = a.driver_id
        return initial

    def _context(self, tr, form, available_vehicles_qs, overlapping):
        return {
            'tr': tr,
            'form': form,
            'vehicles_with_info': _vehicles_with_info(available_vehicles_qs),
            'overlapping': overlapping,
            'is_late': tr.is_late_booking,
            'is_editing': tr.status == 'Approved',
        }

    def get(self, request, pk):
        from settings_app.models import Settings
        site_settings = Settings.load()
        tr = self._get_tr(pk)
        avail_v, avail_d = self._availability(tr, site_settings)
        overlapping = get_overlapping_trips(tr.district, tr.period_from, tr.period_to, nudge_days=site_settings.nudge_window_days()).exclude(pk=tr.pk)
        initial = self._initial_from_assignments(tr) if tr.status == 'Approved' else None
        form = RequestApprovalForm(
            num_vehicles=tr.num_vehicles, available_vehicles=avail_v,
            available_drivers=avail_d, initial=initial,
        )
        return render(request, self.template_name, self._context(tr, form, avail_v, overlapping))

    def post(self, request, pk):
        from settings_app.models import Settings
        site_settings = Settings.load()
        tr = self._get_tr(pk)
        was_approved = tr.status == 'Approved'
        action = request.POST.get('action')
        avail_v, avail_d = self._availability(tr, site_settings)
        overlapping = get_overlapping_trips(tr.district, tr.period_from, tr.period_to, nudge_days=site_settings.nudge_window_days()).exclude(pk=tr.pk)

        if action == 'reject':
            # Rejecting frees any vehicles/drivers previously assigned to this request.
            tr.assignments.all().delete()
            tr.status = 'Rejected'
            tr.admin_comment = request.POST.get('admin_comment', '')
            tr.save()
            sync_fleet_statuses()
            messages.success(request, f'Request #{tr.pk} rejected.')
            return redirect('bookings:request_queue')

        if action == 'approve':
            form = RequestApprovalForm(
                request.POST,
                num_vehicles=tr.num_vehicles,
                available_vehicles=avail_v,
                available_drivers=avail_d,
            )
            if not form.is_valid():
                return render(request, self.template_name, self._context(tr, form, avail_v, overlapping))

            # Replace assignments wholesale — covers both first approval and re-editing.
            tr.assignments.all().delete()
            for vehicle, driver in form.assignment_pairs():
                TripAssignment.objects.create(transport_request=tr, vehicle=vehicle, driver=driver)
            tr.status = 'Approved'
            tr.admin_comment = form.cleaned_data.get('admin_comment', '')
            if not tr.approved_date:
                tr.approved_date = datetime.date.today()
            tr.save()
            # Reconcile in case re-assignment changed which vehicles/drivers are
            # tied to an active trip (e.g. editing a trip that's already underway).
            sync_fleet_statuses()
            verb = 'updated' if was_approved else 'approved'
            messages.success(request, f'Request #{tr.pk} {verb}.')
            return redirect('bookings:request_queue')

        return redirect('bookings:request_review', pk=pk)


class FleetHomeView(LoginRequiredMixin, View):
    """Route authenticated users to the Fleet Manager landing page for their role.

    Ported from the standalone fleet project's accounts.HomeView; the Superadmin
    branch now lands on the request queue because fleet user management was
    replaced by ImpTracker's user administration.
    """

    def get(self, request):
        user = request.user
        if user.is_superuser or user.groups.filter(name__in=['Superadmin', 'Fleet Manager']).exists():
            return redirect(reverse_lazy('bookings:request_queue'))
        if user.groups.filter(name='Requester').exists():
            return redirect(reverse_lazy('bookings:my_requests'))
        if user.groups.filter(name='Dashboard Viewer').exists():
            return redirect(reverse_lazy('dashboard:dashboard'))
        # Ungrouped users see a neutral home page rather than an error.
        return render(request, 'fleet/home.html')
