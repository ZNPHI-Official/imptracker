import datetime
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import Driver, FuelRecord, MaintenanceRecord, Vehicle

User = get_user_model()


def make_vehicle(**kwargs):
    defaults = dict(
        make='Toyota',
        model='Hilux',
        year=2020,
        license_plate='ZM 001 AB',
        vehicle_type='Hilux',
        current_mileage=50000,
        seating_capacity=5,
        fuel_type='Diesel',
        status='Available',
        maintenance_interval_km=5000,
    )
    defaults.update(kwargs)
    return Vehicle.objects.create(**defaults)


def make_driver(**kwargs):
    defaults = dict(name='Driver 1', phone='', status='Available')
    defaults.update(kwargs)
    return Driver.objects.create(**defaults)


def make_user(username, group_name):
    user = User.objects.create_user(username=username, password='testpass123')
    group, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(group)
    return user


class VehicleModelTest(TestCase):

    def test_str_representation(self):
        v = make_vehicle()
        self.assertEqual(str(v), '2020 Toyota Hilux (ZM 001 AB)')

    def test_license_plate_unique(self):
        make_vehicle(license_plate='ZM 999 XY')
        with self.assertRaises(Exception):
            make_vehicle(license_plate='ZM 999 XY')

    def test_default_status_is_available(self):
        v = make_vehicle()
        self.assertEqual(v.status, 'Available')

    def test_default_maintenance_interval(self):
        v = make_vehicle()
        self.assertEqual(v.maintenance_interval_km, 5000)

    def test_maintenance_status_green(self):
        v = make_vehicle(current_mileage=50000, maintenance_interval_km=5000,
                         last_service_mileage=46000)
        # km_until_service = (46000 + 5000) - 50000 = 1000 → green
        self.assertEqual(v.maintenance_status, 'green')

    def test_maintenance_status_amber(self):
        v = make_vehicle(current_mileage=50000, maintenance_interval_km=5000,
                         last_service_mileage=46000)
        # Let's make it tighter: last_service=45600, interval=5000 → next=50600, current=50200 → 400 → amber
        v.last_service_mileage = 45600
        v.current_mileage = 50200
        v.save()
        self.assertEqual(v.maintenance_status, 'amber')

    def test_maintenance_status_red(self):
        v = make_vehicle(current_mileage=55000, maintenance_interval_km=5000,
                         last_service_mileage=49000)
        # km_until_service = (49000 + 5000) - 55000 = -1000 → red
        self.assertEqual(v.maintenance_status, 'red')

    def test_maintenance_status_unknown_when_no_service_record(self):
        v = make_vehicle(last_service_mileage=None)
        self.assertEqual(v.maintenance_status, 'unknown')

    def test_km_until_service_none_without_baseline(self):
        v = make_vehicle(last_service_mileage=None)
        self.assertIsNone(v.km_until_service)

    def test_km_until_service_calculated_correctly(self):
        v = make_vehicle(current_mileage=50000, maintenance_interval_km=5000,
                         last_service_mileage=47000)
        self.assertEqual(v.km_until_service, 2000)

    def test_ordering_by_license_plate(self):
        make_vehicle(license_plate='ZM 002 BB')
        make_vehicle(license_plate='ZM 001 AA')
        plates = list(Vehicle.objects.values_list('license_plate', flat=True))
        self.assertEqual(plates, sorted(plates))


class DriverModelTest(TestCase):

    def test_str_representation(self):
        d = make_driver(name='Driver 5')
        self.assertEqual(str(d), 'Driver 5')

    def test_default_status_is_available(self):
        d = make_driver()
        self.assertEqual(d.status, 'Available')

    def test_phone_optional(self):
        d = Driver.objects.create(name='Driver 2')
        self.assertEqual(d.phone, '')

    def test_ordering_by_name(self):
        make_driver(name='Driver 3')
        make_driver(name='Driver 1')
        names = list(Driver.objects.values_list('name', flat=True))
        self.assertEqual(names, sorted(names))


class FuelRecordModelTest(TestCase):

    def setUp(self):
        self.vehicle = make_vehicle()

    def test_str_representation(self):
        fr = FuelRecord.objects.create(
            vehicle=self.vehicle,
            date=datetime.date(2026, 3, 1),
            liters=50,
            cost_per_liter='2.50',
            total_cost='125.00',
            location='Lusaka',
            mileage_at_fillup=50000,
        )
        self.assertIn('Fuel:', str(fr))
        self.assertIn('50', str(fr))

    def test_notes_optional(self):
        fr = FuelRecord.objects.create(
            vehicle=self.vehicle,
            date=datetime.date(2026, 3, 1),
            liters=40,
            cost_per_liter='2.50',
            total_cost='100.00',
            location='Kabwe',
            mileage_at_fillup=51000,
        )
        self.assertEqual(fr.notes, '')

    def test_ordering_newest_first(self):
        FuelRecord.objects.create(
            vehicle=self.vehicle, date=datetime.date(2026, 1, 1),
            liters=40, cost_per_liter='2.5', total_cost='100',
            location='X', mileage_at_fillup=48000,
        )
        FuelRecord.objects.create(
            vehicle=self.vehicle, date=datetime.date(2026, 3, 1),
            liters=50, cost_per_liter='2.5', total_cost='125',
            location='Y', mileage_at_fillup=50000,
        )
        dates = list(FuelRecord.objects.values_list('date', flat=True))
        self.assertEqual(dates, sorted(dates, reverse=True))


class MaintenanceRecordModelTest(TestCase):

    def setUp(self):
        self.vehicle = make_vehicle(current_mileage=50000, last_service_mileage=None)

    def test_str_representation(self):
        mr = MaintenanceRecord.objects.create(
            vehicle=self.vehicle,
            date=datetime.date(2026, 3, 10),
            mileage_at_service=48000,
            service_type='Oil change',
            cost='500.00',
            vendor='QuickFix Garage',
        )
        self.assertIn('Maintenance:', str(mr))
        self.assertIn('Oil change', str(mr))

    def test_notes_optional(self):
        mr = MaintenanceRecord.objects.create(
            vehicle=self.vehicle,
            date=datetime.date(2026, 3, 10),
            mileage_at_service=48000,
            service_type='Full service',
            cost='1200.00',
            vendor='Toyota Zambia',
        )
        self.assertEqual(mr.notes, '')

    def test_signal_updates_vehicle_last_service(self):
        """Creating a MaintenanceRecord must automatically update the vehicle's baseline."""
        self.assertIsNone(self.vehicle.last_service_date)
        MaintenanceRecord.objects.create(
            vehicle=self.vehicle,
            date=datetime.date(2026, 3, 10),
            mileage_at_service=48000,
            service_type='Oil change',
            cost='500.00',
            vendor='QuickFix Garage',
        )
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.last_service_date, datetime.date(2026, 3, 10))
        self.assertEqual(self.vehicle.last_service_mileage, 48000)

    def test_signal_uses_latest_record(self):
        """If two MaintenanceRecords exist, the vehicle reflects the most recent one."""
        MaintenanceRecord.objects.create(
            vehicle=self.vehicle,
            date=datetime.date(2026, 1, 1),
            mileage_at_service=45000,
            service_type='Oil change',
            cost='500.00',
            vendor='Garage A',
        )
        MaintenanceRecord.objects.create(
            vehicle=self.vehicle,
            date=datetime.date(2026, 4, 1),
            mileage_at_service=50000,
            service_type='Full service',
            cost='1200.00',
            vendor='Garage B',
        )
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.last_service_mileage, 50000)
        self.assertEqual(self.vehicle.last_service_date, datetime.date(2026, 4, 1))

    def test_vehicle_maintenance_status_after_service(self):
        """After a service record is created, maintenance_status should reflect the new baseline."""
        self.vehicle.current_mileage = 50000
        self.vehicle.maintenance_interval_km = 5000
        self.vehicle.save()

        MaintenanceRecord.objects.create(
            vehicle=self.vehicle,
            date=datetime.date(2026, 4, 1),
            mileage_at_service=50000,
            service_type='Full service',
            cost='1200.00',
            vendor='Toyota Zambia',
        )
        self.vehicle.refresh_from_db()
        # km_until_service = (50000 + 5000) - 50000 = 5000 → green
        self.assertEqual(self.vehicle.maintenance_status, 'green')


# ---------------------------------------------------------------------------
# Phase 5: Vehicle and maintenance management — new tests
# ---------------------------------------------------------------------------

class MaintenanceBlockingTest(TestCase):
    """Phase 4's get_available_vehicles() must exclude overdue vehicles."""

    def test_overdue_vehicle_excluded_from_availability(self):
        from bookings.views import get_available_vehicles

        overdue = make_vehicle(
            license_plate='ZM OVERDUE',
            current_mileage=55000,
            last_service_mileage=49000,
            maintenance_interval_km=5000,
        )
        # km_until_service = (49000 + 5000) - 55000 = -1000 → red/overdue
        self.assertEqual(overdue.maintenance_status, 'red')

        period_from = datetime.date.today() + datetime.timedelta(days=7)
        period_to = period_from + datetime.timedelta(days=2)
        available = get_available_vehicles(period_from, period_to)

        self.assertNotIn(overdue, list(available))

    def test_green_vehicle_not_blocked(self):
        from bookings.views import get_available_vehicles

        good = make_vehicle(
            license_plate='ZM GOOD',
            current_mileage=50000,
            last_service_mileage=46000,
            maintenance_interval_km=5000,
        )
        # km_until_service = 1000 → green
        self.assertEqual(good.maintenance_status, 'green')

        period_from = datetime.date.today() + datetime.timedelta(days=7)
        period_to = period_from + datetime.timedelta(days=2)
        available = get_available_vehicles(period_from, period_to)

        self.assertIn(good, list(available))

    def test_vehicle_with_no_service_record_not_blocked(self):
        """Unknown maintenance status is not treated as overdue."""
        from bookings.views import get_available_vehicles

        v = make_vehicle(license_plate='ZM NOSVC', last_service_mileage=None)
        self.assertEqual(v.maintenance_status, 'unknown')

        period_from = datetime.date.today() + datetime.timedelta(days=7)
        period_to = period_from + datetime.timedelta(days=2)
        available = get_available_vehicles(period_from, period_to)

        self.assertIn(v, list(available))


class MaintenanceStatusAutoFlipTest(TestCase):
    """Logging a MaintenanceRecord for an 'In Maintenance' vehicle must flip it to 'Available'."""

    def setUp(self):
        self.fm = make_user('fleet_mgr', 'Fleet Manager')
        self.vehicle = make_vehicle(
            license_plate='ZM MAINT',
            status='In Maintenance',
            current_mileage=60000,
            last_service_mileage=54000,
            maintenance_interval_km=5000,
        )

    def test_maintenance_record_flips_status_to_available(self):
        self.client.login(username='fleet_mgr', password='testpass123')
        response = self.client.post(
            reverse('fleet:maintenance_record_add', kwargs={'pk': self.vehicle.pk}),
            {
                'date': '2026-06-20',
                'mileage_at_service': '60000',
                'service_type': 'Full service',
                'cost': '1500.00',
                'vendor': 'Toyota Zambia',
                'notes': '',
            },
        )
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'Available')
        self.assertRedirects(response, reverse('fleet:vehicle_detail', kwargs={'pk': self.vehicle.pk}))

    def test_maintenance_record_does_not_flip_emergency_standby(self):
        """Emergency Standby status is set manually and must not be overridden."""
        self.vehicle.status = 'Emergency Standby'
        self.vehicle.save()
        self.client.login(username='fleet_mgr', password='testpass123')
        self.client.post(
            reverse('fleet:maintenance_record_add', kwargs={'pk': self.vehicle.pk}),
            {
                'date': '2026-06-20',
                'mileage_at_service': '60000',
                'service_type': 'Oil change',
                'cost': '500.00',
                'vendor': 'Garage',
                'notes': '',
            },
        )
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'Emergency Standby')

    def test_maintenance_record_updates_baseline(self):
        self.client.login(username='fleet_mgr', password='testpass123')
        self.client.post(
            reverse('fleet:maintenance_record_add', kwargs={'pk': self.vehicle.pk}),
            {
                'date': '2026-06-20',
                'mileage_at_service': '60000',
                'service_type': 'Full service',
                'cost': '1500.00',
                'vendor': 'Toyota Zambia',
                'notes': '',
            },
        )
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.last_service_mileage, 60000)
        self.assertEqual(self.vehicle.last_service_date, datetime.date(2026, 6, 20))


class VehicleViewAccessTest(TestCase):
    """Role-based access control for fleet views."""

    def setUp(self):
        self.vehicle = make_vehicle(license_plate='ZM ACCESS')
        self.fm = make_user('fleet_mgr', 'Fleet Manager')
        self.viewer = make_user('dash_viewer', 'Dashboard Viewer')
        self.requester = make_user('requester', 'Requester')

    def test_vehicle_list_accessible_to_fleet_manager(self):
        self.client.login(username='fleet_mgr', password='testpass123')
        response = self.client.get(reverse('fleet:vehicle_list'))
        self.assertEqual(response.status_code, 200)

    def test_vehicle_list_accessible_to_dashboard_viewer(self):
        self.client.login(username='dash_viewer', password='testpass123')
        response = self.client.get(reverse('fleet:vehicle_list'))
        self.assertEqual(response.status_code, 200)

    def test_vehicle_list_forbidden_to_requester(self):
        self.client.login(username='requester', password='testpass123')
        response = self.client.get(reverse('fleet:vehicle_list'))
        self.assertEqual(response.status_code, 403)

    def test_vehicle_edit_forbidden_to_dashboard_viewer(self):
        self.client.login(username='dash_viewer', password='testpass123')
        response = self.client.get(reverse('fleet:vehicle_edit', kwargs={'pk': self.vehicle.pk}))
        self.assertEqual(response.status_code, 403)

    def test_vehicle_edit_accessible_to_fleet_manager(self):
        self.client.login(username='fleet_mgr', password='testpass123')
        response = self.client.get(reverse('fleet:vehicle_edit', kwargs={'pk': self.vehicle.pk}))
        self.assertEqual(response.status_code, 200)

    def test_fuel_record_add_forbidden_to_dashboard_viewer(self):
        self.client.login(username='dash_viewer', password='testpass123')
        response = self.client.post(
            reverse('fleet:fuel_record_add', kwargs={'pk': self.vehicle.pk}), {}
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_redirected_to_login(self):
        response = self.client.get(reverse('fleet:vehicle_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])


class DriverViewAccessTest(TestCase):

    def setUp(self):
        self.driver = make_driver(name='Driver Test')
        self.fm = make_user('fleet_mgr2', 'Fleet Manager')
        self.viewer = make_user('dash_viewer2', 'Dashboard Viewer')
        self.requester = make_user('requester2', 'Requester')

    def test_driver_list_accessible_to_fleet_manager(self):
        self.client.login(username='fleet_mgr2', password='testpass123')
        response = self.client.get(reverse('fleet:driver_list'))
        self.assertEqual(response.status_code, 200)

    def test_driver_list_accessible_to_dashboard_viewer(self):
        self.client.login(username='dash_viewer2', password='testpass123')
        response = self.client.get(reverse('fleet:driver_list'))
        self.assertEqual(response.status_code, 200)

    def test_driver_list_forbidden_to_requester(self):
        self.client.login(username='requester2', password='testpass123')
        response = self.client.get(reverse('fleet:driver_list'))
        self.assertEqual(response.status_code, 403)

    def test_driver_edit_forbidden_to_dashboard_viewer(self):
        self.client.login(username='dash_viewer2', password='testpass123')
        response = self.client.get(reverse('fleet:driver_edit', kwargs={'pk': self.driver.pk}))
        self.assertEqual(response.status_code, 403)

    def test_driver_edit_saves_status_change(self):
        self.client.login(username='fleet_mgr2', password='testpass123')
        response = self.client.post(
            reverse('fleet:driver_edit', kwargs={'pk': self.driver.pk}),
            {'name': 'Driver Test', 'phone': '', 'status': 'On Leave'},
        )
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.status, 'On Leave')
        self.assertRedirects(response, reverse('fleet:driver_list'))


# ---------------------------------------------------------------------------
# Phase 9: Vehicle and Driver create views
# ---------------------------------------------------------------------------

class VehicleCreateViewTest(TestCase):

    def setUp(self):
        self.fm = make_user('fm_create', 'Fleet Manager')
        self.viewer = make_user('dv_create', 'Dashboard Viewer')
        self.add_url = reverse('fleet:vehicle_add')
        self.valid_data = {
            'make': 'Toyota',
            'model': 'Land Cruiser',
            'year': 2024,
            'license_plate': 'ZM NEW 01',
            'vehicle_type': 'Land Cruiser',
            'fuel_type': 'Diesel',
            'seating_capacity': 7,
            'status': 'Available',
            'current_mileage': 0,
            'maintenance_interval_km': 5000,
        }

    def test_get_form_accessible_to_fleet_manager(self):
        self.client.force_login(self.fm)
        self.assertEqual(self.client.get(self.add_url).status_code, 200)

    def test_get_form_forbidden_to_dashboard_viewer(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.add_url).status_code, 403)

    def test_valid_post_creates_vehicle(self):
        self.client.force_login(self.fm)
        self.client.post(self.add_url, self.valid_data)
        self.assertTrue(Vehicle.objects.filter(license_plate='ZM NEW 01').exists())

    def test_valid_post_redirects_to_detail(self):
        self.client.force_login(self.fm)
        response = self.client.post(self.add_url, self.valid_data)
        vehicle = Vehicle.objects.get(license_plate='ZM NEW 01')
        self.assertRedirects(response, reverse('fleet:vehicle_detail', kwargs={'pk': vehicle.pk}))

    def test_duplicate_license_plate_shows_error(self):
        make_vehicle(license_plate='ZM DUP 99')
        self.client.force_login(self.fm)
        data = dict(self.valid_data, license_plate='ZM DUP 99')
        response = self.client.post(self.add_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vehicle.objects.filter(license_plate='ZM DUP 99').count() > 1)


class DriverCreateViewTest(TestCase):

    def setUp(self):
        self.fm = make_user('fm_driver_create', 'Fleet Manager')
        self.viewer = make_user('dv_driver_create', 'Dashboard Viewer')
        self.add_url = reverse('fleet:driver_add')

    def test_get_form_accessible_to_fleet_manager(self):
        self.client.force_login(self.fm)
        self.assertEqual(self.client.get(self.add_url).status_code, 200)

    def test_get_form_forbidden_to_dashboard_viewer(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.add_url).status_code, 403)

    def test_valid_post_creates_driver(self):
        self.client.force_login(self.fm)
        self.client.post(self.add_url, {'name': 'New Driver', 'phone': '0977000000', 'status': 'Available'})
        self.assertTrue(Driver.objects.filter(name='New Driver').exists())

    def test_valid_post_redirects_to_driver_list(self):
        self.client.force_login(self.fm)
        response = self.client.post(self.add_url, {'name': 'New Driver 2', 'phone': '', 'status': 'Available'})
        self.assertRedirects(response, reverse('fleet:driver_list'))

    def test_missing_name_shows_error(self):
        self.client.force_login(self.fm)
        response = self.client.post(self.add_url, {'name': '', 'phone': '', 'status': 'Available'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Driver.objects.filter(name='').count(), 0)


class VehicleListSortingTest(TestCase):

    def setUp(self):
        self.fm = make_user('sort_fm', 'Fleet Manager')
        self.client.force_login(self.fm)
        # Distinct values across every sortable column.
        self.b = make_vehicle(license_plate='BBB 222', vehicle_type='Land Cruiser',
                              current_mileage=20000, last_service_mileage=18000,
                              maintenance_interval_km=5000, status='On Trip')  # km_to_service = 3000
        self.a = make_vehicle(license_plate='AAA 111', vehicle_type='Hilux',
                              current_mileage=80000, last_service_mileage=78000,
                              maintenance_interval_km=5000, status='Available')  # km_to_service = 3000
        self.c = make_vehicle(license_plate='CCC 333', vehicle_type='Hilux',
                              current_mileage=10000, last_service_mileage=9000,
                              maintenance_interval_km=5000, status='In Maintenance')  # km_to_service = 4000

    def _plates(self, **params):
        response = self.client.get(reverse('fleet:vehicle_list'), params)
        return [v.license_plate for v in response.context['vehicles']]

    def test_default_sort_is_plate_ascending(self):
        self.assertEqual(self._plates(), ['AAA 111', 'BBB 222', 'CCC 333'])

    def test_sort_by_plate_descending(self):
        self.assertEqual(self._plates(sort='plate', dir='desc'), ['CCC 333', 'BBB 222', 'AAA 111'])

    def test_sort_by_mileage_ascending(self):
        # current_mileage: CCC=10000, BBB=20000, AAA=80000
        self.assertEqual(self._plates(sort='mileage', dir='asc'), ['CCC 333', 'BBB 222', 'AAA 111'])

    def test_sort_by_km_to_service_descending(self):
        # km_to_service: BBB=3000, AAA=3000, CCC=4000 → CCC first when desc
        self.assertEqual(self._plates(sort='service', dir='desc')[0], 'CCC 333')

    def test_invalid_sort_falls_back_to_default(self):
        self.assertEqual(self._plates(sort='not_a_field'), ['AAA 111', 'BBB 222', 'CCC 333'])


class DriverListSortingTest(TestCase):

    def setUp(self):
        self.fm = make_user('sort_fm2', 'Fleet Manager')
        self.client.force_login(self.fm)
        make_driver(name='Charlie', status='Available')
        make_driver(name='Alice', status='On Leave')
        make_driver(name='Bob', status='On Assignment')

    def _names(self, **params):
        response = self.client.get(reverse('fleet:driver_list'), params)
        return [d.name for d in response.context['drivers']]

    def test_default_sort_is_name_ascending(self):
        self.assertEqual(self._names(), ['Alice', 'Bob', 'Charlie'])

    def test_sort_by_name_descending(self):
        self.assertEqual(self._names(sort='name', dir='desc'), ['Charlie', 'Bob', 'Alice'])

    def test_sort_by_status_ascending(self):
        # status alphabetical: Available, On Assignment, On Leave → Charlie, Bob, Alice
        self.assertEqual(self._names(sort='status', dir='asc'), ['Charlie', 'Bob', 'Alice'])
