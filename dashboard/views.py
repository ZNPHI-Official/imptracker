import calendar
import csv
import datetime
import json
from decimal import Decimal

from django.db.models import Avg, Count, Max, Min, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.generic import View

from accounts.mixins import GroupRequiredMixin
from bookings.models import Province, TransportRequest, TripAssignment
from fleet.models import FuelRecord, MaintenanceRecord, Vehicle

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

GANTT_GROUPS = ['Fleet Manager', 'Dashboard Viewer', 'Superadmin']
DASHBOARD_GROUPS = ['Fleet Manager', 'Dashboard Viewer', 'Superadmin']

_TOTAL_DAYS = 14

# Three district names differ between our DB fixture and the GeoJSON adm2_name field.
_DISTRICT_NAME_MAP = {
    'Chiengi': 'Chienge',
    'Senga': 'Senga Hill',
    "Shang'ombo": 'Shangombo',
}

_INTERVAL_DAYS = {
    '7d': 7,
    '30d': 30,
    '90d': 90,
    '6m': 182,
    '1y': 365,
}

INTERVAL_OPTIONS = [
    ('7d', '7 days'),
    ('30d', '30 days'),
    ('90d', '90 days'),
    ('6m', '6 months'),
    ('1y', '1 year'),
]


def _parse_interval(interval_str, today):
    """Return (period_start, period_end, days) from an interval key string."""
    days = _INTERVAL_DAYS.get(interval_str, 30)
    return today - datetime.timedelta(days=days), today, days


# ---------------------------------------------------------------------------
# Gantt chart (Phase 6)
# ---------------------------------------------------------------------------

def _gantt_block(period_from, period_to, window_start, status, pk, label):
    """Compute percentage-based CSS position of a booking block within the Gantt window."""
    start_day = max((period_from - window_start).days, 0)
    end_day = min((period_to - window_start).days + 1, _TOTAL_DAYS)
    return {
        'left_pct': round(start_day / _TOTAL_DAYS * 100, 4),
        'width_pct': round((end_day - start_day) / _TOTAL_DAYS * 100, 4),
        'status': status,
        'pk': pk,
        'label': label,
    }


class GanttView(GroupRequiredMixin, View):
    group_required = GANTT_GROUPS
    template_name = 'dashboard/gantt.html'

    def get(self, request):
        from_str = request.GET.get('from')
        try:
            window_start = datetime.date.fromisoformat(from_str)
        except (TypeError, ValueError):
            window_start = datetime.date.today()

        window_end = window_start + datetime.timedelta(days=_TOTAL_DAYS - 1)

        today = datetime.date.today()
        today_col_num = (today - window_start).days
        today_in_window = 0 <= today_col_num < _TOTAL_DAYS

        days = []
        for i in range(_TOTAL_DAYS):
            d = window_start + datetime.timedelta(days=i)
            days.append({
                'date': d,
                'is_today': d == today,
                'is_weekend': d.weekday() >= 5,
            })

        province_id = request.GET.get('province') or None
        if province_id:
            try:
                province_id = int(province_id)
            except ValueError:
                province_id = None

        provinces = Province.objects.order_by('name')
        vehicles = Vehicle.objects.order_by('make', 'model', 'license_plate')

        # Approved / In Progress / Completed assignments overlapping the window
        assignment_qs = (
            TripAssignment.objects
            .filter(
                transport_request__status__in=['Approved', 'In Progress', 'Completed'],
                transport_request__period_from__lte=window_end,
                transport_request__period_to__gte=window_start,
            )
            .select_related(
                'vehicle',
                'transport_request',
                'transport_request__province',
                'transport_request__district',
            )
        )
        if province_id:
            assignment_qs = assignment_qs.filter(transport_request__province_id=province_id)

        assignment_map = {}
        for a in assignment_qs:
            assignment_map.setdefault(a.vehicle_id, []).append(a)

        # Submitted requests overlapping the window (no vehicle assigned yet)
        pending_qs = (
            TransportRequest.objects
            .filter(
                status='Submitted',
                period_from__lte=window_end,
                period_to__gte=window_start,
            )
            .select_related('province', 'district')
        )
        if province_id:
            pending_qs = pending_qs.filter(province_id=province_id)

        vehicle_rows = []
        for vehicle in vehicles:
            bookings = []
            for a in assignment_map.get(vehicle.id, []):
                req = a.transport_request
                label = req.district.name if req.district else req.province.name
                bookings.append(
                    _gantt_block(req.period_from, req.period_to, window_start, req.status, req.pk, label)
                )
            vehicle_rows.append({'vehicle': vehicle, 'bookings': bookings})

        pending_blocks = []
        for req in pending_qs:
            label = req.district.name if req.district else req.province.name
            pending_blocks.append(
                _gantt_block(req.period_from, req.period_to, window_start, 'Submitted', req.pk, label)
            )

        can_interact = (
            request.user.groups.filter(name__in=['Fleet Manager', 'Superadmin']).exists()
            or request.user.is_superuser
        )

        context = {
            'window_start': window_start,
            'window_end': window_end,
            'prev_start': window_start - datetime.timedelta(days=_TOTAL_DAYS),
            'next_start': window_start + datetime.timedelta(days=_TOTAL_DAYS),
            'today_in_window': today_in_window,
            'today_col_num': today_col_num,
            'days': days,
            'provinces': provinces,
            'selected_province_id': province_id,
            'vehicle_rows': vehicle_rows,
            'pending_blocks': pending_blocks,
            'can_interact': can_interact,
        }
        return render(request, self.template_name, context)


# ---------------------------------------------------------------------------
# KPI Dashboard (Phase 7)
# ---------------------------------------------------------------------------


class DashboardView(GroupRequiredMixin, View):
    group_required = DASHBOARD_GROUPS
    template_name = 'dashboard/dashboard.html'

    def get(self, request):
        if request.GET.get('export') == 'csv':
            return self._csv_export(request)

        today = datetime.date.today()
        interval = request.GET.get('interval', '30d')
        if interval not in _INTERVAL_DAYS:
            interval = '30d'
        period_start, period_end, period_days = _parse_interval(interval, today)

        # Fetch vehicles once; prefetch fuel records so the projection loop is N+1-free
        vehicles = list(
            Vehicle.objects.prefetch_related('fuel_records').order_by('license_plate')
        )
        vehicle_count = len(vehicles)
        vehicle_id_map = {v.id: v for v in vehicles}

        # ----------------------------------------------------------------
        # KPI 1 — Fleet Utilisation
        # ----------------------------------------------------------------
        total_vehicle_days = vehicle_count * period_days

        assignments_in_period = list(
            TripAssignment.objects
            .filter(
                transport_request__status__in=['Approved', 'In Progress', 'Completed'],
                transport_request__period_to__gte=period_start,
                transport_request__period_from__lte=period_end,
            )
            .select_related('transport_request', 'vehicle')
        )

        vehicle_days_used = 0
        vehicle_day_map = {}
        for a in assignments_in_period:
            req = a.transport_request
            # Clamp trip dates to the selected period window
            effective_start = max(req.period_from, period_start)
            effective_end = min(req.period_to, period_end)
            days = (effective_end - effective_start).days + 1
            vehicle_days_used += days
            vehicle_day_map[a.vehicle_id] = vehicle_day_map.get(a.vehicle_id, 0) + days

        utilization_pct = round(vehicle_days_used / max(1, total_vehicle_days) * 100, 1)

        sorted_by_use = sorted(vehicle_day_map.items(), key=lambda x: x[1], reverse=True)
        most_used = [
            {'vehicle': vehicle_id_map[vid], 'days': d}
            for vid, d in sorted_by_use[:3]
            if vid in vehicle_id_map
        ]
        unused_ids = {v.id for v in vehicles} - set(vehicle_day_map.keys())
        least_used = [{'vehicle': vehicle_id_map[vid], 'days': 0} for vid in list(unused_ids)[:3]]

        # ----------------------------------------------------------------
        # KPI 2 — Request Volume
        # ----------------------------------------------------------------
        # Filter by date_of_request (when the request was submitted), not trip dates,
        # so "request volume" reflects activity during the period.
        raw_requests = list(
            TransportRequest.objects
            .filter(date_of_request__range=(period_start, period_end))
            .values('status', 'period_from', 'date_of_request', 'is_emergency')
        )
        total_requests = len(raw_requests)
        status_counts = {}
        for r in raw_requests:
            status_counts[r['status']] = status_counts.get(r['status'], 0) + 1

        if raw_requests:
            lead_times = [
                (r['period_from'] - r['date_of_request']).days
                for r in raw_requests
            ]
            avg_lead_time = round(sum(lead_times) / len(lead_times), 1)
            # Late booking: submitted less than 14 days before the trip start
            late_count = sum(1 for lt in lead_times if lt < 14)
            late_pct = round(late_count / total_requests * 100, 1)
        else:
            avg_lead_time = 0.0
            late_count = 0
            late_pct = 0.0

        emergency_count = sum(1 for r in raw_requests if r['is_emergency'])

        # Pre-compute individual status counts so the template can access them
        # without dict key lookups (which break for keys containing spaces).
        approved_or_active_count = (
            status_counts.get('Approved', 0)
            + status_counts.get('In Progress', 0)
            + status_counts.get('Completed', 0)
        )
        rejected_count = status_counts.get('Rejected', 0)
        submitted_count = status_counts.get('Submitted', 0)
        cancelled_count = status_counts.get('Cancelled', 0)

        # Trip patterns: department breakdown and top destination districts
        dept_breakdown = list(
            TransportRequest.objects
            .filter(date_of_request__range=(period_start, period_end))
            .values('department__name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        dept_labels = [d['department__name'] or 'Unknown' for d in dept_breakdown]
        dept_counts_data = [d['count'] for d in dept_breakdown]

        raw_top = list(
            TransportRequest.objects
            .filter(
                date_of_request__range=(period_start, period_end),
                status__in=['Approved', 'In Progress', 'Completed'],
            )
            .values('district__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        max_count = raw_top[0]['count'] if raw_top else 1
        top_districts = [
            {**d, 'bar_pct': round(d['count'] / max_count * 100)}
            for d in raw_top
        ]

        # ----------------------------------------------------------------
        # KPI 3 — Maintenance Health
        # ----------------------------------------------------------------
        green_count = sum(1 for v in vehicles if v.maintenance_status == 'green')
        amber_count = sum(1 for v in vehicles if v.maintenance_status == 'amber')
        red_count = sum(1 for v in vehicles if v.maintenance_status == 'red')
        unknown_count = sum(1 for v in vehicles if v.maintenance_status == 'unknown')

        maint_cost_in_period = (
            MaintenanceRecord.objects
            .filter(date__range=(period_start, period_end))
            .aggregate(total=Sum('cost'))['total'] or Decimal('0')
        )
        # Vehicles approaching service but not yet overdue
        upcoming_service_list = [
            v for v in vehicles
            if v.km_until_service is not None and 0 < v.km_until_service <= 1000
        ]

        # ----------------------------------------------------------------
        # KPI 4 — Finance
        # ----------------------------------------------------------------
        fuel_total = (
            FuelRecord.objects
            .filter(date__range=(period_start, period_end))
            .aggregate(total=Sum('total_cost'))['total'] or Decimal('0')
        )
        finance_maint_total = maint_cost_in_period
        total_cost = fuel_total + finance_maint_total

        completed_in_period = TransportRequest.objects.filter(
            status='Completed',
            period_to__gte=period_start,
            period_to__lte=period_end,
        ).count()

        cost_per_trip = round(float(total_cost) / max(1, completed_in_period), 2)
        cost_per_vehicle = round(float(total_cost) / max(1, vehicle_count), 2)

        # Projected maintenance across four planning horizons (1 / 3 / 6 / 12 months).
        # For each vehicle we estimate how many months until its next service is due,
        # then bucket it into whichever horizons it falls within.
        avg_maint_cost = (
            MaintenanceRecord.objects.aggregate(avg=Avg('cost'))['avg'] or Decimal('5000')
        )
        avg_maint_cost_float = float(avg_maint_cost)

        # Collect every vehicle that has a km_until_service value.
        # Overdue vehicles (km_remaining <= 0) count as months=0 for all horizons.
        vehicles_with_months = []
        for v in vehicles:
            km_remaining = v.km_until_service
            if km_remaining is None:
                continue
            if km_remaining <= 0:
                vehicles_with_months.append({'vehicle': v, 'months': 0, 'urgent': True})
                continue

            # Prefer fill-up mileage records for the km/month estimate;
            # fall back to a lifetime average from the build year if fewer than 2 exist.
            fuel_recs = sorted(v.fuel_records.all(), key=lambda r: r.date)
            if len(fuel_recs) >= 2:
                km_span = fuel_recs[-1].mileage_at_fillup - fuel_recs[0].mileage_at_fillup
                day_span = (fuel_recs[-1].date - fuel_recs[0].date).days
                km_per_month = (km_span / day_span * 30.4) if day_span > 0 else 0
            else:
                months_in_service = max(1, (today.year - v.year) * 12 + today.month)
                km_per_month = v.current_mileage / months_in_service

            if km_per_month > 0:
                months_to_service = km_remaining / km_per_month
                # Collect up to 12 months out — covers the widest planning horizon
                if months_to_service <= 12:
                    vehicles_with_months.append({
                        'vehicle': v,
                        'months': round(months_to_service, 1),
                        'urgent': False,
                    })

        # Build per-horizon summary for the template's horizon switcher
        _HORIZONS = [
            {'months': 1,  'label': '1 month',   'short': '1m'},
            {'months': 3,  'label': '3 months',  'short': '3m'},
            {'months': 6,  'label': '6 months',  'short': '6m'},
            {'months': 12, 'label': '12 months', 'short': '12m'},
        ]
        projection_horizons = []
        for h in _HORIZONS:
            due = [p for p in vehicles_with_months if p['months'] <= h['months']]
            projection_horizons.append({
                'months':        h['months'],
                'label':         h['label'],
                'short':         h['short'],
                'vehicle_count': len(due),
                'cost':          round(avg_maint_cost_float * len(due)),
            })

        # Keep a backwards-compatible alias used by existing tests (3-month bucket)
        projected_list = [p for p in vehicles_with_months if p['months'] <= 3]
        projected_cost = round(avg_maint_cost_float * len(projected_list))

        # Month toggle — one button per calendar month present in the full dataset.
        # Advance by adding 4 days past the 28th to reliably cross into the next month.
        date_range = TransportRequest.objects.aggregate(
            earliest=Min('date_of_request'),
            latest=Max('date_of_request'),
        )
        available_months = []
        if date_range['earliest']:
            cursor = date_range['earliest'].replace(day=1)
            end_month = min(date_range['latest'], today).replace(day=1)
            while cursor <= end_month:
                available_months.append({
                    'key': cursor.strftime('%Y-%m'),
                    'label': cursor.strftime('%b %Y'),
                })
                cursor = (cursor.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)

        context = {
            'interval': interval,
            'interval_options': INTERVAL_OPTIONS,
            'period_start': period_start,
            'period_end': period_end,
            # KPI 1
            'utilization_pct': utilization_pct,
            'vehicle_count': vehicle_count,
            'total_vehicle_days': total_vehicle_days,
            'vehicle_days_used': vehicle_days_used,
            'most_used': most_used,
            'least_used': least_used,
            # KPI 2
            'total_requests': total_requests,
            'approved_or_active_count': approved_or_active_count,
            'rejected_count': rejected_count,
            'submitted_count': submitted_count,
            'cancelled_count': cancelled_count,
            'avg_lead_time': avg_lead_time,
            'late_count': late_count,
            'late_pct': late_pct,
            'emergency_count': emergency_count,
            'dept_labels_json': json.dumps(dept_labels),
            'dept_counts_json': json.dumps(dept_counts_data),
            'top_districts': top_districts,
            # KPI 3
            'green_count': green_count,
            'amber_count': amber_count,
            'red_count': red_count,
            'unknown_count': unknown_count,
            'maint_cost_in_period': maint_cost_in_period,
            'upcoming_service_list': upcoming_service_list,
            # KPI 4
            'fuel_total': fuel_total,
            'finance_maint_total': finance_maint_total,
            'total_cost': total_cost,
            'cost_per_trip': cost_per_trip,
            'cost_per_vehicle': cost_per_vehicle,
            'projected_list': projected_list,
            'projected_cost': projected_cost,
            'projection_horizons': projection_horizons,
            'avg_maint_cost': round(float(avg_maint_cost), 2),
            # Map
            'available_months': available_months,
        }
        return render(request, self.template_name, context)

    def _csv_export(self, request):
        """One-file comprehensive dump of fleet activity for the selected interval."""
        today = datetime.date.today()
        interval = request.GET.get('interval', '30d')
        if interval not in _INTERVAL_DAYS:
            interval = '30d'
        period_start, period_end, _ = _parse_interval(interval, today)
        label = dict(INTERVAL_OPTIONS).get(interval, interval)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="dashboard_{interval}_{today}.csv"'
        )
        writer = csv.writer(response)

        # Section 1: Transport Requests active in the period
        writer.writerow([f'TRANSPORT REQUESTS — {label} ({period_start} to {period_end})'])
        writer.writerow([
            'ID', 'Date Submitted', 'Status', 'Emergency',
            'Requester', 'Department', 'Programme / Activity',
            'Period From', 'Period To', 'Duration (days)',
            'Province', 'District', 'Destination',
            '# Vehicles', '# Passengers',
            'Assigned Vehicles', 'Assigned Drivers',
            'Admin Comment',
        ])
        requests_qs = (
            TransportRequest.objects
            .filter(
                period_from__lte=period_end,
                period_to__gte=period_start,
            )
            .select_related('department', 'province', 'district')
            .prefetch_related('assignments__vehicle', 'assignments__driver')
            .order_by('period_from')
        )
        for tr in requests_qs:
            vehicles = ', '.join(a.vehicle.license_plate for a in tr.assignments.all())
            drivers = ', '.join(a.driver.name for a in tr.assignments.all())
            duration = (tr.period_to - tr.period_from).days + 1
            writer.writerow([
                tr.pk, tr.date_of_request, tr.status,
                'Yes' if tr.is_emergency else 'No',
                tr.requester_name, tr.department.name, tr.programme_activity,
                tr.period_from, tr.period_to, duration,
                tr.province.name, tr.district.name, tr.destination,
                tr.num_vehicles, tr.num_passengers,
                vehicles, drivers,
                tr.admin_comment,
            ])

        # Section 2: Fuel Records in period
        writer.writerow([])
        writer.writerow([f'FUEL RECORDS — {label} ({period_start} to {period_end})'])
        writer.writerow(['Date', 'Vehicle', 'Location', 'Litres', 'Cost per Litre (K)', 'Total Cost (K)', 'Mileage (km)', 'Notes'])
        for r in (
            FuelRecord.objects
            .filter(date__range=(period_start, period_end))
            .select_related('vehicle')
            .order_by('date')
        ):
            writer.writerow([
                r.date, r.vehicle.license_plate, r.location,
                r.liters, r.cost_per_liter, r.total_cost, r.mileage_at_fillup, r.notes,
            ])

        # Section 3: Maintenance Records in period
        writer.writerow([])
        writer.writerow([f'MAINTENANCE RECORDS — {label} ({period_start} to {period_end})'])
        writer.writerow(['Date', 'Vehicle', 'Mileage at Service (km)', 'Service Type', 'Cost (K)', 'Vendor', 'Notes'])
        for r in (
            MaintenanceRecord.objects
            .filter(date__range=(period_start, period_end))
            .select_related('vehicle')
            .order_by('date')
        ):
            writer.writerow([
                r.date, r.vehicle.license_plate, r.mileage_at_service,
                r.service_type, r.cost, r.vendor, r.notes,
            ])

        return response


class DistrictDataView(GroupRequiredMixin, View):
    """JSON endpoint consumed by Leaflet to colour the choropleth map.

    Accepts ?interval=30d (same keys as the KPI selector) or ?month=YYYY-MM
    to restrict the count to a single calendar month.
    """
    group_required = DASHBOARD_GROUPS

    def get(self, request):
        today = datetime.date.today()
        month_str = request.GET.get('month')

        if month_str:
            try:
                year_s, mon_s = month_str.split('-')
                year, mon = int(year_s), int(mon_s)
                period_start = datetime.date(year, mon, 1)
                period_end = datetime.date(year, mon, calendar.monthrange(year, mon)[1])
            except (ValueError, TypeError, AttributeError):
                month_str = None

        if not month_str:
            interval = request.GET.get('interval', '30d')
            if interval not in _INTERVAL_DAYS:
                interval = '30d'
            period_start, period_end, _ = _parse_interval(interval, today)

        district_counts = (
            TransportRequest.objects
            .filter(
                status__in=['Approved', 'In Progress', 'Completed'],
                period_from__lte=period_end,
                period_to__gte=period_start,
            )
            .values('district__name')
            .annotate(count=Count('id'))
        )

        result = {}
        for row in district_counts:
            db_name = row['district__name']
            if db_name:
                geojson_name = _DISTRICT_NAME_MAP.get(db_name, db_name)
                result[geojson_name] = row['count']

        return JsonResponse(result)
