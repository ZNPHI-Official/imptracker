import datetime
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse

from bookings.models import Department, District, Province, TransportRequest, TripAssignment
from dashboard.views import _gantt_block
from fleet.models import Driver, FuelRecord, MaintenanceRecord, Vehicle

User = get_user_model()

GANTT_URL     = reverse('dashboard:gantt')
DASHBOARD_URL = reverse('dashboard:dashboard')
DISTRICT_URL  = reverse('dashboard:district_data')


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_user(username, group_name):
    user = User.objects.create_user(username=username, password='pass')
    group, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(group)
    return user


def make_vehicle(plate='ZM TEST 001'):
    return Vehicle.objects.create(
        make='Toyota', model='Hilux', year=2020,
        license_plate=plate,
        vehicle_type='Hilux', current_mileage=10000,
        seating_capacity=5, fuel_type='Diesel',
        status='Available', maintenance_interval_km=5000,
    )


def make_driver(name='Test Driver'):
    return Driver.objects.create(name=name, status='Available')


def make_request(province, district, period_from, period_to, status='Approved', department=None):
    if department is None:
        department, _ = Department.objects.get_or_create(name='Test Dept')
    return TransportRequest.objects.create(
        requester_name='Test User',
        department=department,
        position='Officer',
        programme_activity='Activity',
        destination='Destination',
        province=province,
        district=district,
        period_from=period_from,
        period_to=period_to,
        num_vehicles=1,
        num_drivers=1,
        num_passengers=2,
        status=status,
    )


def make_assignment(transport_request, vehicle, driver):
    return TripAssignment.objects.create(
        transport_request=transport_request,
        vehicle=vehicle,
        driver=driver,
    )


# ---------------------------------------------------------------------------
# _gantt_block unit tests
# ---------------------------------------------------------------------------

class GanttBlockTest(TestCase):
    def setUp(self):
        self.window_start = datetime.date(2026, 6, 22)

    def test_block_spanning_full_window(self):
        block = _gantt_block(
            datetime.date(2026, 6, 22), datetime.date(2026, 7, 5),
            self.window_start, 'Approved', 1, 'Lusaka',
        )
        self.assertEqual(block['left_pct'], 0.0)
        self.assertAlmostEqual(block['width_pct'], 100.0, places=1)

    def test_block_starts_at_day_zero(self):
        # Single-day trip on the first day of the window.
        block = _gantt_block(
            datetime.date(2026, 6, 22), datetime.date(2026, 6, 22),
            self.window_start, 'Approved', 1, 'Lusaka',
        )
        self.assertEqual(block['left_pct'], 0.0)
        self.assertAlmostEqual(block['width_pct'], 100 / 14, places=1)

    def test_block_clamped_when_starts_before_window(self):
        # Trip started 3 days before window
        block = _gantt_block(
            datetime.date(2026, 6, 19), datetime.date(2026, 6, 24),
            self.window_start, 'In Progress', 2, 'Ndola',
        )
        self.assertEqual(block['left_pct'], 0.0)
        # Ends on day 2 of window (6/24 - 6/22 = 2, so end_day = 3)
        self.assertGreater(block['width_pct'], 0)

    def test_block_clamped_when_ends_after_window(self):
        # Trip ends 3 days after window
        block = _gantt_block(
            datetime.date(2026, 6, 30), datetime.date(2026, 7, 10),
            self.window_start, 'Approved', 3, 'Kitwe',
        )
        self.assertLess(block['left_pct'], 100.0)
        total = block['left_pct'] + block['width_pct']
        self.assertAlmostEqual(total, 100.0, places=1)

    def test_block_in_middle_of_window(self):
        # Days 2-4 (0-indexed) in the window
        block = _gantt_block(
            datetime.date(2026, 6, 24), datetime.date(2026, 6, 26),
            self.window_start, 'Approved', 4, 'Kabwe',
        )
        expected_left = 2 / 14 * 100
        expected_width = 3 / 14 * 100  # 3 days inclusive
        self.assertAlmostEqual(block['left_pct'], expected_left, places=1)
        self.assertAlmostEqual(block['width_pct'], expected_width, places=1)


# ---------------------------------------------------------------------------
# Access control tests
# ---------------------------------------------------------------------------

class GanttAccessTest(TestCase):
    def test_fleet_manager_can_access(self):
        user = make_user('fm', 'Fleet Manager')
        self.client.force_login(user)
        response = self.client.get(GANTT_URL)
        self.assertEqual(response.status_code, 200)

    def test_dashboard_viewer_can_access(self):
        user = make_user('dv', 'Dashboard Viewer')
        self.client.force_login(user)
        response = self.client.get(GANTT_URL)
        self.assertEqual(response.status_code, 200)

    def test_superadmin_can_access(self):
        user = make_user('sa', 'Superadmin')
        self.client.force_login(user)
        response = self.client.get(GANTT_URL)
        self.assertEqual(response.status_code, 200)

    def test_requester_cannot_access(self):
        user = make_user('req', 'Requester')
        self.client.force_login(user)
        response = self.client.get(GANTT_URL)
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(GANTT_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])


# ---------------------------------------------------------------------------
# Data query and filtering tests
# ---------------------------------------------------------------------------

class GanttQueryTest(TestCase):
    def setUp(self):
        self.fm = make_user('fm', 'Fleet Manager')
        self.client.force_login(self.fm)

        self.province_lsk = Province.objects.create(name='Lusaka')
        self.province_cp = Province.objects.create(name='Copperbelt')
        self.district_lsk = District.objects.create(name='Lusaka', province=self.province_lsk)
        self.district_kb = District.objects.create(name='Kitwe', province=self.province_cp)

        self.vehicle = make_vehicle('ZM-001')
        self.driver = make_driver()

        # Window: 2026-07-01 to 2026-07-14
        self.window_from = '2026-07-01'
        self.window_start = datetime.date(2026, 7, 1)

    def _get(self, **params):
        params.setdefault('from', self.window_from)
        return self.client.get(GANTT_URL, params)

    def test_approved_assignment_appears_in_vehicle_row(self):
        req = make_request(self.province_lsk, self.district_lsk,
                           datetime.date(2026, 7, 3), datetime.date(2026, 7, 5), status='Approved')
        make_assignment(req, self.vehicle, self.driver)

        response = self._get()
        rows = response.context['vehicle_rows']
        vehicle_row = next(r for r in rows if r['vehicle'].pk == self.vehicle.pk)
        self.assertEqual(len(vehicle_row['bookings']), 1)
        self.assertEqual(vehicle_row['bookings'][0]['status'], 'Approved')

    def test_in_progress_assignment_appears_in_vehicle_row(self):
        req = make_request(self.province_lsk, self.district_lsk,
                           datetime.date(2026, 7, 2), datetime.date(2026, 7, 4), status='In Progress')
        make_assignment(req, self.vehicle, self.driver)

        response = self._get()
        rows = response.context['vehicle_rows']
        vehicle_row = next(r for r in rows if r['vehicle'].pk == self.vehicle.pk)
        self.assertEqual(vehicle_row['bookings'][0]['status'], 'In Progress')

    def test_submitted_request_appears_in_pending_blocks(self):
        make_request(self.province_lsk, self.district_lsk,
                     datetime.date(2026, 7, 6), datetime.date(2026, 7, 8), status='Submitted')

        response = self._get()
        self.assertEqual(len(response.context['pending_blocks']), 1)
        self.assertEqual(response.context['pending_blocks'][0]['status'], 'Submitted')

    def test_assignment_outside_window_not_shown(self):
        req = make_request(self.province_lsk, self.district_lsk,
                           datetime.date(2026, 7, 20), datetime.date(2026, 7, 25), status='Approved')
        make_assignment(req, self.vehicle, self.driver)

        response = self._get()
        rows = response.context['vehicle_rows']
        vehicle_row = next(r for r in rows if r['vehicle'].pk == self.vehicle.pk)
        self.assertEqual(len(vehicle_row['bookings']), 0)

    def test_province_filter_excludes_other_provinces(self):
        # Approved trip to Lusaka
        req_lsk = make_request(self.province_lsk, self.district_lsk,
                                datetime.date(2026, 7, 3), datetime.date(2026, 7, 5), status='Approved')
        v2 = make_vehicle('ZM-002')
        d2 = make_driver('Driver B')
        make_assignment(req_lsk, self.vehicle, self.driver)

        # Approved trip to Copperbelt
        req_cb = make_request(self.province_cp, self.district_kb,
                               datetime.date(2026, 7, 3), datetime.date(2026, 7, 5), status='Approved')
        make_assignment(req_cb, v2, d2)

        response = self._get(province=self.province_lsk.pk)

        all_bookings = [b for r in response.context['vehicle_rows'] for b in r['bookings']]
        pks = [b['pk'] for b in all_bookings]

        self.assertIn(req_lsk.pk, pks)
        self.assertNotIn(req_cb.pk, pks)

    def test_province_filter_applies_to_pending_blocks(self):
        make_request(self.province_lsk, self.district_lsk,
                     datetime.date(2026, 7, 6), datetime.date(2026, 7, 8), status='Submitted')
        make_request(self.province_cp, self.district_kb,
                     datetime.date(2026, 7, 6), datetime.date(2026, 7, 8), status='Submitted')

        response = self._get(province=self.province_lsk.pk)
        self.assertEqual(len(response.context['pending_blocks']), 1)
        self.assertEqual(response.context['pending_blocks'][0]['label'], 'Lusaka')

    def test_rejected_request_does_not_appear(self):
        req = make_request(self.province_lsk, self.district_lsk,
                           datetime.date(2026, 7, 3), datetime.date(2026, 7, 5), status='Rejected')
        # Even if there were an assignment, rejected should not show.
        response = self._get()
        all_bookings = [b for r in response.context['vehicle_rows'] for b in r['bookings']]
        self.assertEqual(len(all_bookings), 0)
        self.assertEqual(len(response.context['pending_blocks']), 0)

    def test_all_vehicles_appear_as_rows_regardless_of_bookings(self):
        # Even vehicles with no bookings should have a row.
        response = self._get()
        rows = response.context['vehicle_rows']
        row_vehicle_pks = {r['vehicle'].pk for r in rows}
        self.assertIn(self.vehicle.pk, row_vehicle_pks)

    def test_dashboard_viewer_cannot_interact(self):
        dv = make_user('dv', 'Dashboard Viewer')
        self.client.force_login(dv)
        response = self._get()
        self.assertFalse(response.context['can_interact'])

    def test_fleet_manager_can_interact(self):
        response = self._get()
        self.assertTrue(response.context['can_interact'])


# ===========================================================================
# Phase 7 — KPI Dashboard tests
# ===========================================================================

# Shared fixtures reused across all Phase 7 test classes
def _make_province(name='Lusaka'):
    return Province.objects.create(name=name)

def _make_district(name='Lusaka', province=None):
    if province is None:
        province = _make_province()
    return District.objects.create(name=name, province=province)

def _make_dept(name='Epidemiology'):
    dept, _ = Department.objects.get_or_create(name=name)
    return dept

def _make_vehicle_with_service(plate='ZM-KPI-001', current_mileage=10000,
                               last_service_mileage=5000, interval_km=5000):
    return Vehicle.objects.create(
        make='Toyota', model='Hilux', year=2022,
        license_plate=plate, vehicle_type='Hilux',
        current_mileage=current_mileage, seating_capacity=5,
        fuel_type='Diesel', status='Available',
        maintenance_interval_km=interval_km,
        last_service_mileage=last_service_mileage,
    )


class DashboardAccessTest(TestCase):
    """Access control mirrors the Gantt — FM/DV/Superadmin in, Requester/unauth out."""

    def test_fleet_manager_can_access(self):
        user = make_user('fm7', 'Fleet Manager')
        self.client.force_login(user)
        self.assertEqual(self.client.get(DASHBOARD_URL).status_code, 200)

    def test_dashboard_viewer_can_access(self):
        user = make_user('dv7', 'Dashboard Viewer')
        self.client.force_login(user)
        self.assertEqual(self.client.get(DASHBOARD_URL).status_code, 200)

    def test_superadmin_can_access(self):
        user = make_user('sa7', 'Superadmin')
        self.client.force_login(user)
        self.assertEqual(self.client.get(DASHBOARD_URL).status_code, 200)

    def test_requester_cannot_access(self):
        user = make_user('req7', 'Requester')
        self.client.force_login(user)
        self.assertEqual(self.client.get(DASHBOARD_URL).status_code, 403)

    def test_unauthenticated_redirects(self):
        response = self.client.get(DASHBOARD_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])


class DashboardKPIUtilisationTest(TestCase):
    """KPI 1 — fleet utilisation calculation."""

    def setUp(self):
        self.fm = make_user('fm_u', 'Fleet Manager')
        self.client.force_login(self.fm)
        self.province = _make_province('Central')
        self.district = _make_district('Kabwe', self.province)
        self.vehicle = _make_vehicle_with_service('ZM-U-001')
        self.driver = make_driver('Driver U')

    def test_utilisation_zero_with_no_trips(self):
        response = self.client.get(DASHBOARD_URL, {'interval': '7d'})
        self.assertEqual(response.context['utilization_pct'], 0.0)
        self.assertEqual(response.context['vehicle_days_used'], 0)

    def test_utilisation_calculated_for_completed_trip_in_period(self):
        today = datetime.date.today()
        # A 3-day completed trip fully inside the 7-day window
        req = make_request(self.province, self.district,
                           today - datetime.timedelta(days=5),
                           today - datetime.timedelta(days=3),
                           status='Completed')
        make_assignment(req, self.vehicle, self.driver)

        response = self.client.get(DASHBOARD_URL, {'interval': '7d'})
        self.assertEqual(response.context['vehicle_days_used'], 3)
        self.assertGreater(response.context['utilization_pct'], 0)

    def test_trip_outside_period_not_counted(self):
        today = datetime.date.today()
        # Trip 30 days ago — outside the 7-day window
        req = make_request(self.province, self.district,
                           today - datetime.timedelta(days=30),
                           today - datetime.timedelta(days=28),
                           status='Completed')
        make_assignment(req, self.vehicle, self.driver)

        response = self.client.get(DASHBOARD_URL, {'interval': '7d'})
        self.assertEqual(response.context['vehicle_days_used'], 0)


class DashboardKPIRequestVolumeTest(TestCase):
    """KPI 2 — request volume, lead time, and late booking logic."""

    def setUp(self):
        self.fm = make_user('fm_v', 'Fleet Manager')
        self.client.force_login(self.fm)
        self.province = _make_province('Southern')
        self.district = _make_district('Monze', self.province)
        self.today = datetime.date.today()

    def _make_req(self, days_ago_submitted, days_until_trip, status='Submitted'):
        submitted_date = self.today - datetime.timedelta(days=days_ago_submitted)
        period_from = submitted_date + datetime.timedelta(days=days_until_trip)
        period_to = period_from + datetime.timedelta(days=2)
        req = make_request(self.province, self.district, period_from, period_to, status=status)
        # Backdate date_of_request to simulate submission in the past
        TransportRequest.objects.filter(pk=req.pk).update(date_of_request=submitted_date)
        return req

    def test_request_count_in_period(self):
        self._make_req(days_ago_submitted=3, days_until_trip=20)
        self._make_req(days_ago_submitted=5, days_until_trip=30)
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        # Both submitted within the last 30 days
        self.assertEqual(response.context['total_requests'], 2)

    def test_request_outside_period_not_counted(self):
        self._make_req(days_ago_submitted=40, days_until_trip=50)
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        self.assertEqual(response.context['total_requests'], 0)

    def test_late_booking_detected(self):
        # Submitted 5 days ago, trip starts in 7 days: lead time = 12 < 14 → late
        self._make_req(days_ago_submitted=5, days_until_trip=7)
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        self.assertEqual(response.context['late_count'], 1)
        self.assertGreater(response.context['late_pct'], 0)

    def test_on_time_booking_not_flagged(self):
        # Lead time = 20 days → not late
        self._make_req(days_ago_submitted=3, days_until_trip=20)
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        self.assertEqual(response.context['late_count'], 0)


class DashboardKPIMaintenanceTest(TestCase):
    """KPI 3 — maintenance traffic light counts and cost aggregation."""

    def setUp(self):
        self.fm = make_user('fm_m', 'Fleet Manager')
        self.client.force_login(self.fm)

    def test_traffic_light_counts_are_correct(self):
        # Green: 5,000 km remaining (10000 mileage, last service at 5000, interval 5000 → km_until = 0... wait)
        # Let me recalculate: km_until_service = last_service_mileage + interval - current_mileage
        # Green: last=0, interval=10000, current=1000 → km_until = 9000 → green
        # Amber: last=0, interval=10000, current=9600 → km_until = 400 → amber (<=500)
        # Red:   last=0, interval=5000,  current=6000 → km_until = -1000 → red
        _make_vehicle_with_service('ZM-M-001', current_mileage=1000,
                                   last_service_mileage=0, interval_km=10000)
        _make_vehicle_with_service('ZM-M-002', current_mileage=9600,
                                   last_service_mileage=0, interval_km=10000)
        _make_vehicle_with_service('ZM-M-003', current_mileage=6000,
                                   last_service_mileage=0, interval_km=5000)

        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        self.assertEqual(response.context['green_count'], 1)
        self.assertEqual(response.context['amber_count'], 1)
        self.assertEqual(response.context['red_count'], 1)

    def test_maintenance_cost_aggregated_in_period(self):
        vehicle = _make_vehicle_with_service('ZM-M-010')
        today = datetime.date.today()
        MaintenanceRecord.objects.create(
            vehicle=vehicle, date=today - datetime.timedelta(days=5),
            mileage_at_service=8000, service_type='Oil change',
            cost=Decimal('1500.00'), vendor='Garage A',
        )
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        self.assertEqual(response.context['maint_cost_in_period'], Decimal('1500.00'))

    def test_maintenance_cost_outside_period_excluded(self):
        vehicle = _make_vehicle_with_service('ZM-M-011')
        today = datetime.date.today()
        MaintenanceRecord.objects.create(
            vehicle=vehicle, date=today - datetime.timedelta(days=60),
            mileage_at_service=5000, service_type='Tyres',
            cost=Decimal('3000.00'), vendor='Garage B',
        )
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        self.assertEqual(response.context['maint_cost_in_period'], Decimal('0'))


class DashboardKPIFinanceTest(TestCase):
    """KPI 4 — fuel/maintenance totals and projected maintenance."""

    def setUp(self):
        self.fm = make_user('fm_f', 'Fleet Manager')
        self.client.force_login(self.fm)
        self.vehicle = _make_vehicle_with_service('ZM-F-001')
        self.today = datetime.date.today()

    def test_fuel_total_in_period(self):
        FuelRecord.objects.create(
            vehicle=self.vehicle,
            date=self.today - datetime.timedelta(days=10),
            liters=Decimal('50.00'), cost_per_liter=Decimal('30.00'),
            total_cost=Decimal('1500.00'), location='Lusaka',
            mileage_at_fillup=10500,
        )
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        self.assertEqual(response.context['fuel_total'], Decimal('1500.00'))

    def test_fuel_record_outside_period_excluded(self):
        FuelRecord.objects.create(
            vehicle=self.vehicle,
            date=self.today - datetime.timedelta(days=60),
            liters=Decimal('50.00'), cost_per_liter=Decimal('30.00'),
            total_cost=Decimal('1500.00'), location='Ndola',
            mileage_at_fillup=9000,
        )
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        self.assertEqual(response.context['fuel_total'], Decimal('0'))

    def test_projected_maintenance_flags_vehicle_due_within_3_months(self):
        # Vehicle with 1500 km remaining, last service at 0, current 3500, interval 5000
        # km_until_service = 0 + 5000 - 3500 = 1500 km remaining
        # Fuel records: driven 500 km over 30 days → 500 km/month → due in 3 months
        v = _make_vehicle_with_service('ZM-F-002', current_mileage=3500,
                                       last_service_mileage=0, interval_km=5000)
        base = self.today - datetime.timedelta(days=30)
        FuelRecord.objects.create(
            vehicle=v, date=base, liters=Decimal('40'), cost_per_liter=Decimal('30'),
            total_cost=Decimal('1200'), location='L', mileage_at_fillup=3000,
        )
        FuelRecord.objects.create(
            vehicle=v, date=self.today, liters=Decimal('40'), cost_per_liter=Decimal('30'),
            total_cost=Decimal('1200'), location='L', mileage_at_fillup=3500,
        )
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        proj_pks = [p['vehicle'].pk for p in response.context['projected_list']]
        self.assertIn(v.pk, proj_pks)

    def test_vehicle_with_ample_km_not_projected(self):
        # 8,000 km remaining at 500 km/month → ~16 months → outside 3-month window
        v = _make_vehicle_with_service('ZM-F-003', current_mileage=2000,
                                       last_service_mileage=0, interval_km=10000)
        base = self.today - datetime.timedelta(days=30)
        FuelRecord.objects.create(
            vehicle=v, date=base, liters=Decimal('40'), cost_per_liter=Decimal('30'),
            total_cost=Decimal('1200'), location='L', mileage_at_fillup=1500,
        )
        FuelRecord.objects.create(
            vehicle=v, date=self.today, liters=Decimal('40'), cost_per_liter=Decimal('30'),
            total_cost=Decimal('1200'), location='L', mileage_at_fillup=2000,
        )
        response = self.client.get(DASHBOARD_URL, {'interval': '30d'})
        proj_pks = [p['vehicle'].pk for p in response.context['projected_list']]
        self.assertNotIn(v.pk, proj_pks)


class DistrictDataViewTest(TestCase):
    """Tests for the JSON endpoint consumed by Leaflet."""

    def setUp(self):
        self.fm = make_user('fm_d', 'Fleet Manager')
        self.client.force_login(self.fm)
        self.province = _make_province('Luapula')
        self.district = _make_district('Mansa', self.province)
        self.today = datetime.date.today()

    def _make_approved_req(self, period_from, period_to, district=None):
        d = district or self.district
        p = d.province
        return make_request(p, d, period_from, period_to, status='Approved')

    def test_returns_json(self):
        response = self.client.get(DISTRICT_URL, {'interval': '30d'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_approved_trip_in_period_counted(self):
        self._make_approved_req(
            self.today - datetime.timedelta(days=5),
            self.today + datetime.timedelta(days=2),
        )
        response = self.client.get(DISTRICT_URL, {'interval': '30d'})
        data = json.loads(response.content)
        self.assertEqual(data.get('Mansa'), 1)

    def test_trip_outside_interval_excluded(self):
        self._make_approved_req(
            self.today - datetime.timedelta(days=40),
            self.today - datetime.timedelta(days=35),
        )
        response = self.client.get(DISTRICT_URL, {'interval': '30d'})
        data = json.loads(response.content)
        self.assertIsNone(data.get('Mansa'))

    def test_month_filter_returns_only_that_month(self):
        # Trip in April 2026 — should appear with month=2026-04
        self._make_approved_req(
            datetime.date(2026, 4, 10), datetime.date(2026, 4, 15),
        )
        # Trip in May 2026 — should NOT appear with month=2026-04
        self._make_approved_req(
            datetime.date(2026, 5, 10), datetime.date(2026, 5, 15),
        )
        response = self.client.get(DISTRICT_URL, {'month': '2026-04'})
        data = json.loads(response.content)
        self.assertEqual(data.get('Mansa'), 1)

    def test_district_name_mapping_for_chiengi(self):
        # 'Chiengi' in DB should appear as 'Chienge' in the JSON output
        prov = _make_province('Luapula-Chiengi')
        dist = _make_district('Chiengi', prov)
        self._make_approved_req(
            self.today - datetime.timedelta(days=5),
            self.today + datetime.timedelta(days=2),
            district=dist,
        )
        response = self.client.get(DISTRICT_URL, {'interval': '30d'})
        data = json.loads(response.content)
        self.assertIn('Chienge', data)
        self.assertNotIn('Chiengi', data)

    def test_submitted_request_not_counted(self):
        make_request(
            self.province, self.district,
            self.today - datetime.timedelta(days=5),
            self.today + datetime.timedelta(days=2),
            status='Submitted',
        )
        response = self.client.get(DISTRICT_URL, {'interval': '30d'})
        data = json.loads(response.content)
        self.assertIsNone(data.get('Mansa'))

    def test_requester_cannot_access_district_data(self):
        req_user = make_user('req_d', 'Requester')
        self.client.force_login(req_user)
        self.assertEqual(self.client.get(DISTRICT_URL).status_code, 403)
