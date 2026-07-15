import datetime
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Province, District, Department, TransportRequest, TripAssignment
from .views import get_available_drivers, get_available_vehicles, get_overlapping_trips
from .services import sync_fleet_statuses
from fleet.models import Vehicle, Driver

User = get_user_model()


def make_user(username='requester', group_name='Requester', department=None, position='Officer'):
    user = User.objects.create_user(username=username, password='testpass123')
    if group_name:
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
    # Requester details are sourced from the account on the request form.
    user.position = position
    user.department = department if department is not None else make_department()
    user.save()
    return user


def make_province(name='Lusaka'):
    return Province.objects.get_or_create(name=name)[0]


def make_district(province=None, name='Lusaka'):
    if province is None:
        province = make_province()
    return District.objects.get_or_create(name=name, province=province)[0]


def make_department(name='Surveillance and Disease Intelligence'):
    return Department.objects.get_or_create(name=name)[0]


def make_request(province=None, district=None, department=None, **kwargs):
    if province is None:
        province = make_province()
    if district is None:
        district = make_district(province=province)
    if department is None:
        department = make_department()
    defaults = dict(
        requester_name='Alice Banda',
        department=department,
        position='Officer',
        programme_activity='Field visit',
        period_from=datetime.date(2026, 7, 1),
        period_to=datetime.date(2026, 7, 5),
        province=province,
        district=district,
        destination='Lusaka Central',
        num_vehicles=1,
        num_drivers=1,
        num_passengers=3,
    )
    defaults.update(kwargs)
    return TransportRequest.objects.create(**defaults)


def make_vehicle(license_plate='ZM 001 AB'):
    return Vehicle.objects.create(
        make='Toyota', model='Hilux', year=2020,
        license_plate=license_plate, vehicle_type='Hilux',
        current_mileage=50000, seating_capacity=5,
        fuel_type='Diesel',
    )


def make_driver(name='Driver 1'):
    return Driver.objects.create(name=name)


class ProvinceModelTest(TestCase):

    def test_str_representation(self):
        p = make_province('Eastern')
        self.assertEqual(str(p), 'Eastern')

    def test_name_unique(self):
        Province.objects.create(name='Central')
        with self.assertRaises(Exception):
            Province.objects.create(name='Central')

    def test_ordering_by_name(self):
        Province.objects.create(name='Western')
        Province.objects.create(name='Central')
        names = list(Province.objects.values_list('name', flat=True))
        self.assertEqual(names, sorted(names))


class DistrictModelTest(TestCase):

    def test_str_representation(self):
        d = make_district(name='Chipata')
        self.assertEqual(str(d), 'Chipata')

    def test_district_belongs_to_province(self):
        province = make_province('Eastern')
        district = make_district(province=province, name='Chipata')
        self.assertEqual(district.province, province)

    def test_same_name_allowed_in_different_provinces(self):
        p1 = Province.objects.create(name='Province A')
        p2 = Province.objects.create(name='Province B')
        District.objects.create(name='Shared Name', province=p1)
        # Should not raise — same name is only unique per province.
        District.objects.create(name='Shared Name', province=p2)

    def test_duplicate_name_in_same_province_raises(self):
        province = make_province()
        District.objects.create(name='Duplicate', province=province)
        with self.assertRaises(Exception):
            District.objects.create(name='Duplicate', province=province)

    def test_districts_accessible_via_province_reverse(self):
        province = make_province('Copperbelt')
        District.objects.create(name='Ndola', province=province)
        District.objects.create(name='Kitwe', province=province)
        self.assertEqual(province.districts.count(), 2)

    def test_ordering_by_name(self):
        province = make_province()
        District.objects.create(name='Ndola', province=province)
        District.objects.create(name='Kitwe', province=province)
        names = list(province.districts.values_list('name', flat=True))
        self.assertEqual(names, sorted(names))


class DepartmentModelTest(TestCase):

    def test_str_representation(self):
        d = Department.objects.create(name='Emergency Preparedness and Response')
        self.assertEqual(str(d), 'Emergency Preparedness and Response')

    def test_name_unique(self):
        Department.objects.create(name='NPHLS')
        with self.assertRaises(Exception):
            Department.objects.create(name='NPHLS')


class TransportRequestModelTest(TestCase):

    def test_str_representation(self):
        req = make_request()
        self.assertIn('Alice Banda', str(req))
        self.assertIn('Submitted', str(req))

    def test_default_status_is_submitted(self):
        req = make_request()
        self.assertEqual(req.status, 'Submitted')

    def test_default_emergency_flag_false(self):
        req = make_request()
        self.assertFalse(req.is_emergency)

    def test_date_of_request_auto_set(self):
        req = make_request()
        self.assertEqual(req.date_of_request, datetime.date.today())

    def test_is_late_booking_true_when_under_two_weeks(self):
        soon = datetime.date.today() + datetime.timedelta(days=7)
        req = make_request(period_from=soon, period_to=soon + datetime.timedelta(days=2))
        self.assertTrue(req.is_late_booking)

    def test_is_late_booking_false_when_over_two_weeks(self):
        far = datetime.date.today() + datetime.timedelta(weeks=3)
        req = make_request(period_from=far, period_to=far + datetime.timedelta(days=5))
        self.assertFalse(req.is_late_booking)

    def test_department_relationship(self):
        dept = make_department('Field Epidemiology Program')
        req = make_request(department=dept)
        self.assertEqual(req.department.name, 'Field Epidemiology Program')

    def test_province_and_district_relationship(self):
        province = Province.objects.create(name='Northern')
        district = District.objects.create(name='Kasama', province=province)
        req = make_request(province=province, district=district)
        self.assertEqual(req.province.name, 'Northern')
        self.assertEqual(req.district.name, 'Kasama')

    def test_coordination_fields_default(self):
        req = make_request()
        self.assertFalse(req.coordination_acknowledged)
        self.assertEqual(req.coordination_note, '')

    def test_ordering_newest_first(self):
        # Two requests created sequentially — second should appear first.
        make_request()
        make_request()
        ids = list(TransportRequest.objects.values_list('id', flat=True))
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_cancel_status_transition(self):
        req = make_request()
        req.status = 'Cancelled'
        req.save()
        req.refresh_from_db()
        self.assertEqual(req.status, 'Cancelled')


class TripAssignmentModelTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.request = make_request(province=self.province, district=self.district)
        self.vehicle = make_vehicle()
        self.driver = make_driver()

    def test_str_representation(self):
        ta = TripAssignment.objects.create(
            transport_request=self.request,
            vehicle=self.vehicle,
            driver=self.driver,
        )
        self.assertIn(str(self.vehicle), str(ta))
        self.assertIn(str(self.driver), str(ta))

    def test_multiple_assignments_per_request(self):
        """A single request can have multiple vehicle/driver pairs."""
        vehicle2 = make_vehicle(license_plate='ZM 002 BB')
        driver2 = make_driver(name='Driver 2')

        TripAssignment.objects.create(
            transport_request=self.request, vehicle=self.vehicle, driver=self.driver
        )
        TripAssignment.objects.create(
            transport_request=self.request, vehicle=vehicle2, driver=driver2
        )
        self.assertEqual(self.request.assignments.count(), 2)

    def test_assignment_links_to_vehicle_and_driver(self):
        ta = TripAssignment.objects.create(
            transport_request=self.request, vehicle=self.vehicle, driver=self.driver
        )
        self.assertEqual(ta.vehicle, self.vehicle)
        self.assertEqual(ta.driver, self.driver)

    def test_assignments_accessible_from_vehicle(self):
        TripAssignment.objects.create(
            transport_request=self.request, vehicle=self.vehicle, driver=self.driver
        )
        self.assertEqual(self.vehicle.assignments.count(), 1)

    def test_assignments_accessible_from_driver(self):
        TripAssignment.objects.create(
            transport_request=self.request, vehicle=self.vehicle, driver=self.driver
        )
        self.assertEqual(self.driver.assignments.count(), 1)


# ---------------------------------------------------------------------------
# Phase 3: Form, views, and coordination nudge tests
# ---------------------------------------------------------------------------

def _valid_post_data(province, district, department):
    """Return a minimal valid POST dict for the transport request form.

    Requester details now come from the logged-in account, so the payload only
    carries the activity selection (adhoc by default) and trip details."""
    future = datetime.date.today() + datetime.timedelta(weeks=4)
    return {
        'activity_choice': 'adhoc',
        'adhoc_activity': 'Field Visit',
        'period_from': future.strftime('%Y-%m-%d'),
        'period_to': (future + datetime.timedelta(days=3)).strftime('%Y-%m-%d'),
        'province': str(province.pk),
        'district': str(district.pk),
        'destination': 'Lusaka Central',
        'num_vehicles': '1',
        'num_drivers': '1',
        'num_passengers': '3',
    }


class TransportRequestFormTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()

    def test_valid_form_saves(self):
        from .forms import TransportRequestForm
        data = _valid_post_data(self.province, self.district, self.department)
        form = TransportRequestForm(data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_end_before_start_invalid(self):
        from .forms import TransportRequestForm
        data = _valid_post_data(self.province, self.district, self.department)
        data['period_to'] = (datetime.date.today() + datetime.timedelta(weeks=2)).strftime('%Y-%m-%d')
        data['period_from'] = (datetime.date.today() + datetime.timedelta(weeks=3)).strftime('%Y-%m-%d')
        form = TransportRequestForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn('End date must be on or after the start date', str(form.errors))

    def test_district_wrong_province_invalid(self):
        from .forms import TransportRequestForm
        other_province = Province.objects.create(name='Southern')
        other_district = District.objects.create(name='Choma', province=other_province)
        data = _valid_post_data(self.province, self.district, self.department)
        # Province is Lusaka but district belongs to Southern
        data['province'] = str(self.province.pk)
        data['district'] = str(other_district.pk)
        form = TransportRequestForm(data)
        self.assertFalse(form.is_valid())

    def test_district_queryset_filtered_by_province_in_data(self):
        from .forms import TransportRequestForm
        data = _valid_post_data(self.province, self.district, self.department)
        form = TransportRequestForm(data)
        self.assertIn(self.district, form.fields['district'].queryset)

    def test_missing_required_field_invalid(self):
        from .forms import TransportRequestForm
        data = _valid_post_data(self.province, self.district, self.department)
        del data['activity_choice']
        form = TransportRequestForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn('activity_choice', form.errors)

    def test_adhoc_without_description_invalid(self):
        from .forms import TransportRequestForm
        data = _valid_post_data(self.province, self.district, self.department)
        data['adhoc_activity'] = ''
        form = TransportRequestForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn('adhoc_activity', form.errors)


class DistrictOptionsViewTest(TestCase):

    def setUp(self):
        self.province = make_province('Lusaka')
        self.district = make_district(province=self.province, name='Lusaka')

    def test_returns_districts_for_province(self):
        url = reverse('bookings:district_options')
        response = self.client.get(url, {'province': str(self.province.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lusaka')

    def test_empty_with_no_province(self):
        url = reverse('bookings:district_options')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Lusaka')

    def test_empty_with_invalid_province_id(self):
        url = reverse('bookings:district_options')
        response = self.client.get(url, {'province': 'abc'})
        self.assertEqual(response.status_code, 200)


class TransportRequestCreateViewTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.user = make_user()
        self.client.login(username='requester', password='testpass123')
        self.url = reverse('bookings:request_create')

    def test_get_renders_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'bookings/request_form.html')

    def test_unauthenticated_redirects_to_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertRedirects(response, f'/login/?next={self.url}', fetch_redirect_response=False)

    def test_valid_post_creates_request_no_overlap(self):
        data = _valid_post_data(self.province, self.district, self.department)
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse('bookings:my_requests'), fetch_redirect_response=False)
        self.assertEqual(TransportRequest.objects.count(), 1)
        req = TransportRequest.objects.first()
        self.assertEqual(req.submitted_by, self.user)
        self.assertEqual(req.status, 'Submitted')

    def test_invalid_post_rerenders_form(self):
        data = _valid_post_data(self.province, self.district, self.department)
        data['activity_choice'] = ''
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'bookings/request_form.html')
        self.assertEqual(TransportRequest.objects.count(), 0)

    def test_late_booking_shows_warning_message(self):
        data = _valid_post_data(self.province, self.district, self.department)
        soon = datetime.date.today() + datetime.timedelta(days=5)
        data['period_from'] = soon.strftime('%Y-%m-%d')
        data['period_to'] = (soon + datetime.timedelta(days=2)).strftime('%Y-%m-%d')
        response = self.client.post(self.url, data, follow=True)
        messages = list(response.context['messages'])
        self.assertTrue(any('2 weeks' in str(m) or 'late' in str(m).lower() for m in messages))

    def test_overlap_redirects_to_nudge(self):
        # Create an existing request to the same district in the same timeframe.
        future = datetime.date.today() + datetime.timedelta(weeks=4)
        make_request(
            province=self.province, district=self.district, department=self.department,
            period_from=future, period_to=future + datetime.timedelta(days=3),
            status='Approved',
        )
        data = _valid_post_data(self.province, self.district, self.department)
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse('bookings:coordination_nudge'), fetch_redirect_response=False)
        self.assertIn('pending_request_data', self.client.session)


class CoordinationNudgeViewTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.user = make_user()
        self.client.login(username='requester', password='testpass123')
        self.url = reverse('bookings:coordination_nudge')
        # Seed the session with pending request data, as the create view would.
        future = datetime.date.today() + datetime.timedelta(weeks=4)
        self.raw_data = {
            'activity_choice': 'adhoc',
            'adhoc_activity': 'Field Visit',
            'period_from': future.strftime('%Y-%m-%d'),
            'period_to': (future + datetime.timedelta(days=3)).strftime('%Y-%m-%d'),
            'province': str(self.province.pk),
            'district': str(self.district.pk),
            'destination': 'Lusaka Central',
            'num_vehicles': '1',
            'num_drivers': '1',
            'num_passengers': '3',
        }
        self.overlap = make_request(
            province=self.province, district=self.district, department=self.department,
            period_from=future, period_to=future + datetime.timedelta(days=3),
            status='Approved',
        )

    def _seed_session(self):
        session = self.client.session
        session['pending_request_data'] = self.raw_data
        session['overlapping_trip_ids'] = [self.overlap.pk]
        session['pending_request_is_late'] = False
        session.save()

    def test_get_without_session_redirects_to_form(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('bookings:request_create'), fetch_redirect_response=False)

    def test_get_with_session_renders_nudge_page(self):
        self._seed_session()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'bookings/coordination_nudge.html')

    def test_post_without_acknowledgment_shows_error(self):
        self._seed_session()
        response = self.client.post(self.url, {'coordination_note': 'needed'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TransportRequest.objects.exclude(pk=self.overlap.pk).count(), 0)

    def test_post_with_acknowledgment_creates_request(self):
        self._seed_session()
        response = self.client.post(self.url, {
            'acknowledged': 'on',
            'coordination_note': 'Different programme requirement.',
        })
        self.assertRedirects(response, reverse('bookings:my_requests'), fetch_redirect_response=False)
        new_requests = TransportRequest.objects.exclude(pk=self.overlap.pk)
        self.assertEqual(new_requests.count(), 1)
        req = new_requests.first()
        self.assertTrue(req.coordination_acknowledged)
        self.assertEqual(req.coordination_note, 'Different programme requirement.')

    def test_session_cleared_after_save(self):
        self._seed_session()
        self.client.post(self.url, {'acknowledged': 'on', 'coordination_note': ''})
        session = self.client.session
        self.assertNotIn('pending_request_data', session)


class GetOverlappingTripsTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.other_district = make_district(province=self.province, name='Kafue')
        self.future = datetime.date.today() + datetime.timedelta(weeks=4)

    def test_same_district_within_window_triggers_nudge(self):
        make_request(
            province=self.province, district=self.district,
            period_from=self.future, period_to=self.future + datetime.timedelta(days=2),
            status='Approved',
        )
        result = get_overlapping_trips(self.district, self.future, self.future + datetime.timedelta(days=2))
        self.assertEqual(result.count(), 1)

    def test_different_district_does_not_trigger(self):
        make_request(
            province=self.province, district=self.other_district,
            period_from=self.future, period_to=self.future + datetime.timedelta(days=2),
            status='Approved',
        )
        result = get_overlapping_trips(self.district, self.future, self.future + datetime.timedelta(days=2))
        self.assertEqual(result.count(), 0)

    def test_completed_request_does_not_trigger(self):
        make_request(
            province=self.province, district=self.district,
            period_from=self.future, period_to=self.future + datetime.timedelta(days=2),
            status='Completed',
        )
        result = get_overlapping_trips(self.district, self.future, self.future + datetime.timedelta(days=2))
        self.assertEqual(result.count(), 0)

    def test_far_future_trip_does_not_trigger(self):
        # A trip 30 days away should not trigger the 7-day window nudge.
        far = self.future + datetime.timedelta(days=30)
        make_request(
            province=self.province, district=self.district,
            period_from=far, period_to=far + datetime.timedelta(days=2),
            status='Approved',
        )
        result = get_overlapping_trips(self.district, self.future, self.future + datetime.timedelta(days=2))
        self.assertEqual(result.count(), 0)

    def test_start_and_end_within_window_triggers(self):
        # Both start and end are within the 7-day window of ours → coordination opportunity.
        make_request(
            province=self.province, district=self.district,
            period_from=self.future + datetime.timedelta(days=2),
            period_to=self.future + datetime.timedelta(days=4),
            status='Submitted',
        )
        result = get_overlapping_trips(self.district, self.future, self.future + datetime.timedelta(days=2))
        self.assertEqual(result.count(), 1)

    def test_adjacent_trip_does_not_trigger(self):
        # The regression this fix targets: an existing trip ending the day before
        # ours starts is merely back-to-back, not a coordination opportunity.
        existing_to = self.future - datetime.timedelta(days=1)
        make_request(
            province=self.province, district=self.district,
            period_from=existing_to - datetime.timedelta(days=10),
            period_to=existing_to,
            status='Approved',
        )
        result = get_overlapping_trips(self.district, self.future, self.future + datetime.timedelta(days=2))
        self.assertEqual(result.count(), 0)

    def test_matching_start_but_distant_end_does_not_trigger(self):
        # Same start date, but the existing trip runs far longer → end dates are well
        # outside the window, so under start-AND-end matching it is not flagged.
        make_request(
            province=self.province, district=self.district,
            period_from=self.future,
            period_to=self.future + datetime.timedelta(days=30),
            status='Submitted',
        )
        result = get_overlapping_trips(self.district, self.future, self.future + datetime.timedelta(days=2))
        self.assertEqual(result.count(), 0)


class MyRequestsViewTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.user = make_user()
        self.other_user = make_user(username='other', group_name='Requester')
        self.url = reverse('bookings:my_requests')

    def test_unauthenticated_redirects(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f'/login/?next={self.url}', fetch_redirect_response=False)

    def test_shows_only_own_requests(self):
        own = make_request(province=self.province, district=self.district, submitted_by=self.user)
        make_request(province=self.province, district=self.district, submitted_by=self.other_user)
        self.client.login(username='requester', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        requests_in_context = list(response.context['requests'])
        self.assertEqual(len(requests_in_context), 1)
        self.assertEqual(requests_in_context[0], own)

    def test_empty_state_rendered(self):
        self.client.login(username='requester', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No requests yet')


class TransportRequestDetailViewTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.user = make_user()
        self.other_user = make_user(username='other', group_name='Requester')
        self.req = make_request(
            province=self.province, district=self.district,
            submitted_by=self.user,
        )

    def test_owner_can_view(self):
        self.client.login(username='requester', password='testpass123')
        url = reverse('bookings:request_detail', args=[self.req.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_other_user_gets_404(self):
        self.client.login(username='other', password='testpass123')
        url = reverse('bookings:request_detail', args=[self.req.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_fleet_manager_can_view_any(self):
        manager = make_user(username='manager', group_name='Fleet Manager')
        self.client.login(username='manager', password='testpass123')
        url = reverse('bookings:request_detail', args=[self.req.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class TransportRequestCancelViewTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.user = make_user()
        self.req = make_request(
            province=self.province, district=self.district,
            submitted_by=self.user,
        )
        self.client.login(username='requester', password='testpass123')

    def _cancel(self):
        return self.client.post(reverse('bookings:request_cancel', args=[self.req.pk]))

    def test_cancel_submitted_request(self):
        self._cancel()
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Cancelled')

    def test_cancel_completed_request_rejected(self):
        self.req.status = 'Completed'
        self.req.save()
        self._cancel()
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Completed')

    def test_other_user_cannot_cancel(self):
        other = make_user(username='other2', group_name='Requester')
        self.client.login(username='other2', password='testpass123')
        self.client.post(reverse('bookings:request_cancel', args=[self.req.pk]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Submitted')


# ---------------------------------------------------------------------------
# Phase 4: Availability filtering, queue, and approval workflow tests
# ---------------------------------------------------------------------------

class GetAvailableVehiclesTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.future = datetime.date.today() + datetime.timedelta(weeks=4)

    def test_unbooked_vehicle_is_available(self):
        v = make_vehicle()
        result = get_available_vehicles(self.future, self.future + datetime.timedelta(days=3))
        self.assertIn(v, result)

    def test_booked_vehicle_excluded(self):
        v = make_vehicle()
        driver = make_driver()
        tr = make_request(
            province=self.province, district=self.district, status='Approved',
            period_from=self.future, period_to=self.future + datetime.timedelta(days=3),
        )
        TripAssignment.objects.create(transport_request=tr, vehicle=v, driver=driver)
        result = get_available_vehicles(self.future, self.future + datetime.timedelta(days=3))
        self.assertNotIn(v, result)

    def test_buffer_excludes_adjacent_vehicle(self):
        # Existing trip ends the day before our start. With 1-day buffer, it overlaps.
        v = make_vehicle()
        driver = make_driver()
        existing_end = self.future - datetime.timedelta(days=1)
        tr = make_request(
            province=self.province, district=self.district, status='Approved',
            period_from=existing_end - datetime.timedelta(days=2),
            period_to=existing_end,
        )
        TripAssignment.objects.create(transport_request=tr, vehicle=v, driver=driver)
        result = get_available_vehicles(self.future, self.future + datetime.timedelta(days=3), buffer_days=1)
        self.assertNotIn(v, result)

    def test_vehicle_outside_buffer_is_available(self):
        # Existing trip ends 2 days before our start. With 1-day buffer, no overlap.
        v = make_vehicle()
        driver = make_driver()
        existing_end = self.future - datetime.timedelta(days=2)
        tr = make_request(
            province=self.province, district=self.district, status='Approved',
            period_from=existing_end - datetime.timedelta(days=2),
            period_to=existing_end,
        )
        TripAssignment.objects.create(transport_request=tr, vehicle=v, driver=driver)
        result = get_available_vehicles(self.future, self.future + datetime.timedelta(days=3), buffer_days=1)
        self.assertIn(v, result)

    def test_overdue_maintenance_vehicle_excluded(self):
        # current_mileage (56 000) > last_service (50 000) + interval (5 000) → overdue
        v = Vehicle.objects.create(
            make='Toyota', model='Hilux', year=2020,
            license_plate='ZM RED 01', vehicle_type='Hilux',
            current_mileage=56000, seating_capacity=5, fuel_type='Diesel',
            maintenance_interval_km=5000, last_service_mileage=50000,
        )
        result = get_available_vehicles(self.future, self.future + datetime.timedelta(days=3))
        self.assertNotIn(v, result)

    def test_vehicle_with_no_maintenance_baseline_included(self):
        # last_service_mileage is None → maintenance_status == 'unknown' → not excluded
        v = Vehicle.objects.create(
            make='Toyota', model='Hilux', year=2022,
            license_plate='ZM NEW 01', vehicle_type='Hilux',
            current_mileage=1000, seating_capacity=5, fuel_type='Diesel',
            last_service_mileage=None,
        )
        result = get_available_vehicles(self.future, self.future + datetime.timedelta(days=3))
        self.assertIn(v, result)

    def test_cancelled_trip_does_not_block_vehicle(self):
        v = make_vehicle()
        driver = make_driver()
        tr = make_request(
            province=self.province, district=self.district, status='Cancelled',
            period_from=self.future, period_to=self.future + datetime.timedelta(days=3),
        )
        TripAssignment.objects.create(transport_request=tr, vehicle=v, driver=driver)
        result = get_available_vehicles(self.future, self.future + datetime.timedelta(days=3))
        self.assertIn(v, result)

    def test_rejected_trip_does_not_block_vehicle(self):
        v = make_vehicle()
        driver = make_driver()
        tr = make_request(
            province=self.province, district=self.district, status='Rejected',
            period_from=self.future, period_to=self.future + datetime.timedelta(days=3),
        )
        TripAssignment.objects.create(transport_request=tr, vehicle=v, driver=driver)
        result = get_available_vehicles(self.future, self.future + datetime.timedelta(days=3))
        self.assertIn(v, result)


class GetAvailableDriversTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.future = datetime.date.today() + datetime.timedelta(weeks=4)

    def test_available_driver_returned(self):
        d = make_driver()
        result = get_available_drivers(self.future, self.future + datetime.timedelta(days=3))
        self.assertIn(d, result)

    def test_on_leave_driver_excluded(self):
        d = Driver.objects.create(name='On Leave Driver', status='On Leave')
        result = get_available_drivers(self.future, self.future + datetime.timedelta(days=3))
        self.assertNotIn(d, result)

    def test_driver_assigned_to_overlapping_trip_excluded(self):
        v = make_vehicle()
        d = make_driver()
        tr = make_request(
            province=self.province, district=self.district, status='Approved',
            period_from=self.future, period_to=self.future + datetime.timedelta(days=3),
        )
        TripAssignment.objects.create(transport_request=tr, vehicle=v, driver=d)
        result = get_available_drivers(self.future, self.future + datetime.timedelta(days=3))
        self.assertNotIn(d, result)


class RequestQueueViewTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.manager = make_user(username='manager', group_name='Fleet Manager')
        self.requester = make_user(username='req', group_name='Requester')
        self.url = reverse('bookings:request_queue')

    def test_requester_cannot_access(self):
        self.client.login(username='req', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_fleet_manager_can_access(self):
        self.client.login(username='manager', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'bookings/request_queue.html')

    def test_default_shows_submitted_and_approved(self):
        self.client.login(username='manager', password='testpass123')
        submitted = make_request(province=self.province, district=self.district, status='Submitted')
        approved = make_request(province=self.province, district=self.district, status='Approved')
        response = self.client.get(self.url)
        ctx = list(response.context['requests'])
        self.assertIn(submitted, ctx)
        self.assertIn(approved, ctx)

    def test_in_progress_and_completed_excluded(self):
        self.client.login(username='manager', password='testpass123')
        in_progress = make_request(province=self.province, district=self.district, status='In Progress')
        completed = make_request(province=self.province, district=self.district, status='Completed')
        response = self.client.get(self.url)
        ctx = list(response.context['requests'])
        self.assertNotIn(in_progress, ctx)
        self.assertNotIn(completed, ctx)

    def test_pending_filter_shows_only_submitted(self):
        self.client.login(username='manager', password='testpass123')
        submitted = make_request(province=self.province, district=self.district, status='Submitted')
        approved = make_request(province=self.province, district=self.district, status='Approved')
        response = self.client.get(self.url, {'show': 'pending'})
        ctx = list(response.context['requests'])
        self.assertIn(submitted, ctx)
        self.assertNotIn(approved, ctx)

    def test_approved_filter_shows_only_approved(self):
        self.client.login(username='manager', password='testpass123')
        submitted = make_request(province=self.province, district=self.district, status='Submitted')
        approved = make_request(province=self.province, district=self.district, status='Approved')
        response = self.client.get(self.url, {'show': 'approved'})
        ctx = list(response.context['requests'])
        self.assertNotIn(submitted, ctx)
        self.assertIn(approved, ctx)

    def test_submitted_ordered_before_approved(self):
        self.client.login(username='manager', password='testpass123')
        approved = make_request(province=self.province, district=self.district, status='Approved')
        submitted = make_request(province=self.province, district=self.district, status='Submitted')
        response = self.client.get(self.url)
        ctx = list(response.context['requests'])
        self.assertLess(ctx.index(submitted), ctx.index(approved))

    def test_emergency_requests_ordered_first(self):
        self.client.login(username='manager', password='testpass123')
        future = datetime.date.today() + datetime.timedelta(weeks=4)
        normal = make_request(
            province=self.province, district=self.district,
            period_from=future, period_to=future + datetime.timedelta(days=2),
        )
        emergency = make_request(
            province=self.province, district=self.district,
            period_from=future + datetime.timedelta(days=5),
            period_to=future + datetime.timedelta(days=7),
            is_emergency=True,
        )
        response = self.client.get(self.url)
        ctx = list(response.context['requests'])
        self.assertEqual(ctx[0], emergency)
        self.assertEqual(ctx[1], normal)


class RequestReviewViewTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.manager = make_user(username='manager', group_name='Fleet Manager')
        self.client.login(username='manager', password='testpass123')
        self.future = datetime.date.today() + datetime.timedelta(weeks=4)
        self.tr = make_request(
            province=self.province, district=self.district,
            period_from=self.future, period_to=self.future + datetime.timedelta(days=3),
        )
        self.vehicle = make_vehicle()
        self.driver = make_driver()

    def test_get_renders_review_page(self):
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'bookings/request_review.html')

    def test_approve_creates_assignment(self):
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.post(url, {
            'action': 'approve',
            'vehicle_1': str(self.vehicle.pk),
            'driver_1': str(self.driver.pk),
            'admin_comment': '',
        })
        self.assertRedirects(response, reverse('bookings:request_queue'), fetch_redirect_response=False)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.status, 'Approved')
        self.assertEqual(TripAssignment.objects.filter(transport_request=self.tr).count(), 1)

    def test_approve_sets_approved_date(self):
        url = reverse('bookings:request_review', args=[self.tr.pk])
        self.client.post(url, {
            'action': 'approve',
            'vehicle_1': str(self.vehicle.pk),
            'driver_1': str(self.driver.pk),
            'admin_comment': '',
        })
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.approved_date, datetime.date.today())

    def test_approve_saves_comment(self):
        url = reverse('bookings:request_review', args=[self.tr.pk])
        self.client.post(url, {
            'action': 'approve',
            'vehicle_1': str(self.vehicle.pk),
            'driver_1': str(self.driver.pk),
            'admin_comment': 'Approved — Land Cruiser assigned.',
        })
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.admin_comment, 'Approved — Land Cruiser assigned.')

    def test_reject_updates_status_and_comment(self):
        url = reverse('bookings:request_review', args=[self.tr.pk])
        self.client.post(url, {
            'action': 'reject',
            'admin_comment': 'No vehicles available for this period.',
        })
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.status, 'Rejected')
        self.assertEqual(self.tr.admin_comment, 'No vehicles available for this period.')
        self.assertEqual(TripAssignment.objects.filter(transport_request=self.tr).count(), 0)

    def test_approve_without_vehicle_rerenders_form_with_errors(self):
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.post(url, {
            'action': 'approve',
            'vehicle_1': '',
            'driver_1': str(self.driver.pk),
            'admin_comment': '',
        })
        self.assertEqual(response.status_code, 200)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.status, 'Submitted')
        self.assertEqual(TripAssignment.objects.filter(transport_request=self.tr).count(), 0)

    def test_approved_request_can_be_opened_for_editing(self):
        self.tr.status = 'Approved'
        self.tr.save()
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_editing'])

    def test_in_progress_request_returns_404(self):
        self.tr.status = 'In Progress'
        self.tr.save()
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_completed_request_returns_404(self):
        self.tr.status = 'Completed'
        self.tr.save()
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_editing_approved_replaces_assignment(self):
        # Approve with the first vehicle/driver, then edit to a different pair.
        self.tr.status = 'Approved'
        self.tr.approved_date = datetime.date.today()
        self.tr.save()
        TripAssignment.objects.create(transport_request=self.tr, vehicle=self.vehicle, driver=self.driver)

        new_vehicle = make_vehicle(license_plate='ZM EDIT 02')
        new_driver = make_driver(name='Edited Driver')
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.post(url, {
            'action': 'approve',
            'vehicle_1': str(new_vehicle.pk),
            'driver_1': str(new_driver.pk),
            'admin_comment': 'Reassigned.',
        })
        self.assertRedirects(response, reverse('bookings:request_queue'), fetch_redirect_response=False)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.status, 'Approved')
        assignments = TripAssignment.objects.filter(transport_request=self.tr)
        self.assertEqual(assignments.count(), 1)
        self.assertEqual(assignments.first().vehicle, new_vehicle)
        self.assertEqual(assignments.first().driver, new_driver)

    def test_editing_keeps_currently_assigned_vehicle_selectable(self):
        # A vehicle assigned to this request must remain available while editing it,
        # even though it would otherwise count as 'booked' for this period.
        self.tr.status = 'Approved'
        self.tr.save()
        TripAssignment.objects.create(transport_request=self.tr, vehicle=self.vehicle, driver=self.driver)
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.get(url)
        available = [item['vehicle'] for item in response.context['vehicles_with_info']]
        self.assertIn(self.vehicle, available)

    def test_rejecting_approved_request_releases_assignments(self):
        self.tr.status = 'Approved'
        self.tr.save()
        TripAssignment.objects.create(transport_request=self.tr, vehicle=self.vehicle, driver=self.driver)
        url = reverse('bookings:request_review', args=[self.tr.pk])
        self.client.post(url, {'action': 'reject', 'admin_comment': 'Trip cancelled.'})
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.status, 'Rejected')
        self.assertEqual(TripAssignment.objects.filter(transport_request=self.tr).count(), 0)

    def test_requester_cannot_access_review(self):
        make_user(username='req', group_name='Requester')
        self.client.login(username='req', password='testpass123')
        url = reverse('bookings:request_review', args=[self.tr.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Phase 8: run_transitions management command
# ---------------------------------------------------------------------------

class RunTransitionsCommandTest(TestCase):
    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()

    def _make(self, status, period_from=None, period_to=None):
        today = datetime.date.today()
        return make_request(
            province=self.province,
            district=self.district,
            department=self.department,
            status=status,
            period_from=period_from or today,
            period_to=period_to or today + datetime.timedelta(days=3),
        )

    def test_approved_transitions_to_in_progress_when_started(self):
        tr = self._make('Approved', period_from=datetime.date.today())
        call_command('run_transitions', verbosity=0)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'In Progress')

    def test_in_progress_transitions_to_completed_when_ended(self):
        tr = self._make('In Progress', period_to=datetime.date.today() - datetime.timedelta(days=1))
        call_command('run_transitions', verbosity=0)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'Completed')

    def test_approved_future_trip_not_transitioned(self):
        tr = self._make('Approved', period_from=datetime.date.today() + datetime.timedelta(days=5))
        call_command('run_transitions', verbosity=0)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'Approved')

    def test_submitted_not_transitioned(self):
        tr = self._make('Submitted', period_from=datetime.date.today())
        call_command('run_transitions', verbosity=0)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'Submitted')

    def test_in_progress_ongoing_trip_stays(self):
        """A trip whose end date is today or in the future should not be completed."""
        tr = self._make('In Progress', period_to=datetime.date.today())
        call_command('run_transitions', verbosity=0)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'In Progress')


# ---------------------------------------------------------------------------
# Vehicle/driver status sync with the trip lifecycle
# ---------------------------------------------------------------------------

class SyncFleetStatusesTest(TestCase):

    def setUp(self):
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.today = datetime.date.today()

    def _assign(self, status, vehicle, driver, period_from=None, period_to=None):
        tr = make_request(
            province=self.province, district=self.district, status=status,
            period_from=period_from or self.today,
            period_to=period_to or self.today + datetime.timedelta(days=3),
        )
        TripAssignment.objects.create(transport_request=tr, vehicle=vehicle, driver=driver)
        return tr

    def test_in_progress_marks_vehicle_on_trip_and_driver_on_assignment(self):
        v, d = make_vehicle(), make_driver()
        self._assign('In Progress', v, d)
        sync_fleet_statuses()
        v.refresh_from_db(); d.refresh_from_db()
        self.assertEqual(v.status, 'On Trip')
        self.assertEqual(d.status, 'On Assignment')

    def test_approved_future_trip_does_not_mark_on_trip(self):
        v, d = make_vehicle(), make_driver()
        self._assign('Approved', v, d)
        sync_fleet_statuses()
        v.refresh_from_db(); d.refresh_from_db()
        self.assertEqual(v.status, 'Available')
        self.assertEqual(d.status, 'Available')

    def test_completed_trip_releases_vehicle_and_driver(self):
        v = make_vehicle(); d = make_driver()
        v.status = 'On Trip'; v.save()
        d.status = 'On Assignment'; d.save()
        self._assign('Completed', v, d)
        sync_fleet_statuses()
        v.refresh_from_db(); d.refresh_from_db()
        self.assertEqual(v.status, 'Available')
        self.assertEqual(d.status, 'Available')

    def test_in_maintenance_vehicle_not_overridden(self):
        v = make_vehicle(); v.status = 'In Maintenance'; v.save()
        d = make_driver()
        self._assign('In Progress', v, d)
        sync_fleet_statuses()
        v.refresh_from_db()
        self.assertEqual(v.status, 'In Maintenance')

    def test_emergency_standby_vehicle_not_overridden(self):
        v = make_vehicle(); v.status = 'Emergency Standby'; v.save()
        d = make_driver()
        self._assign('In Progress', v, d)
        sync_fleet_statuses()
        v.refresh_from_db()
        self.assertEqual(v.status, 'Emergency Standby')

    def test_on_leave_driver_not_overridden(self):
        v = make_vehicle()
        d = make_driver(); d.status = 'On Leave'; d.save()
        self._assign('In Progress', v, d)
        sync_fleet_statuses()
        d.refresh_from_db()
        self.assertEqual(d.status, 'On Leave')

    def test_vehicle_on_second_active_trip_stays_on_trip(self):
        # Releasing should consider all of a vehicle's trips, not just one.
        v = make_vehicle(); d = make_driver()
        self._assign('Completed', v, d)
        self._assign('In Progress', v, d)
        sync_fleet_statuses()
        v.refresh_from_db()
        self.assertEqual(v.status, 'On Trip')

    def test_run_transitions_marks_started_trip_on_trip(self):
        # End-to-end: an approved trip starting today flips to In Progress and its
        # vehicle/driver become On Trip / On Assignment in the same command run.
        v, d = make_vehicle(), make_driver()
        self._assign('Approved', v, d, period_from=self.today)
        call_command('run_transitions', verbosity=0)
        v.refresh_from_db(); d.refresh_from_db()
        self.assertEqual(v.status, 'On Trip')
        self.assertEqual(d.status, 'On Assignment')


# ---------------------------------------------------------------------------
# Phase 8: email notification on new request submission
# ---------------------------------------------------------------------------

class NewRequestEmailTest(TestCase):
    def setUp(self):
        from settings_app.models import Settings
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.user = make_user(username='req_email', group_name='Requester')
        self.client.login(username='req_email', password='testpass123')
        four_weeks = datetime.date.today() + datetime.timedelta(weeks=4)
        self.post_data = {
            'activity_choice': 'adhoc',
            'adhoc_activity': 'Email Test Activity',
            'period_from': str(four_weeks),
            'period_to': str(four_weeks + datetime.timedelta(days=5)),
            'province': self.province.pk,
            'district': self.district.pk,
            'destination': 'Lusaka',
            'num_vehicles': 1,
            'num_drivers': 1,
            'num_passengers': 2,
        }
        self.url = reverse('bookings:request_create')
        # Enable email and set address by default; individual tests override as needed.
        s = Settings.load()
        s.email_notifications_enabled = True
        s.notification_email = 'fleet@znphi.gov.zm'
        s.save()

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_sent_when_enabled(self):
        self.client.post(self.url, self.post_data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('fleet@znphi.gov.zm', mail.outbox[0].to)
        self.assertIn('Email Test Activity', mail.outbox[0].subject)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_not_sent_when_disabled(self):
        from settings_app.models import Settings
        s = Settings.load()
        s.email_notifications_enabled = False
        s.save()
        self.client.post(self.url, self.post_data)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_not_sent_when_address_blank(self):
        from settings_app.models import Settings
        s = Settings.load()
        s.notification_email = ''
        s.save()
        self.client.post(self.url, self.post_data)
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# Phase 8: Request Queue CSV export
# ---------------------------------------------------------------------------

class RequestQueueCSVTest(TestCase):
    def setUp(self):
        self.manager = make_user(username='fm_csv', group_name='Fleet Manager')
        self.client.login(username='fm_csv', password='testpass123')
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.tr = make_request(
            province=self.province,
            district=self.district,
            department=self.department,
            status='Submitted',
            programme_activity='CSV Export Test',
        )
        self.url = reverse('bookings:request_queue')

    def test_csv_has_correct_content_type(self):
        response = self.client.get(f'{self.url}?export=csv')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])

    def test_csv_has_content_disposition_header(self):
        response = self.client.get(f'{self.url}?export=csv')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('.csv', response['Content-Disposition'])

    def test_csv_contains_request_data(self):
        response = self.client.get(f'{self.url}?export=csv')
        content = response.content.decode('utf-8')
        self.assertIn('CSV Export Test', content)
        self.assertIn('Programme / Activity', content)

    def test_csv_requester_gets_403(self):
        requester = make_user(username='req_csv', group_name='Requester')
        self.client.login(username='req_csv', password='testpass123')
        response = self.client.get(f'{self.url}?export=csv')
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Programme activity selection from the Implementation Tracker
# ---------------------------------------------------------------------------

class ActivitySelectionTest(TestCase):

    def setUp(self):
        from activities.models import Activity
        from masters.models import ActivityStatus
        self.province = make_province()
        self.district = make_district(province=self.province)
        self.department = make_department()
        self.user = make_user()
        self.client.login(username='requester', password='testpass123')
        self.url = reverse('bookings:request_create')
        status = ActivityStatus.objects.create(name='Planned')
        self.activity = Activity.objects.create(
            activity_id='ACT-001', name='Cholera Response Training', year=2026,
            status=status, planned_month=datetime.date(2026, 8, 1),
            total_budget=1000, responsible_officer=self.user,
        )
        self.other_activity = Activity.objects.create(
            activity_id='ACT-002', name='Not Mine', year=2026,
            status=status, planned_month=datetime.date(2026, 8, 1),
            total_budget=1000,
        )

    def test_form_lists_only_assigned_activities(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'ACT-001')
        self.assertNotContains(response, 'ACT-002')

    def test_selecting_assigned_activity_links_request(self):
        data = _valid_post_data(self.province, self.district, self.department)
        data['activity_choice'] = str(self.activity.pk)
        data.pop('adhoc_activity')
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse('bookings:my_requests'), fetch_redirect_response=False)
        req = TransportRequest.objects.get()
        self.assertEqual(req.activity, self.activity)
        self.assertIn('ACT-001', req.programme_activity)
        # Requester details sourced from the account
        self.assertEqual(req.requester_name, 'requester')
        self.assertEqual(req.position, 'Officer')
        self.assertEqual(req.department, self.user.department)

    def test_unassigned_activity_rejected(self):
        data = _valid_post_data(self.province, self.district, self.department)
        data['activity_choice'] = str(self.other_activity.pk)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TransportRequest.objects.count(), 0)

    def test_adhoc_request_has_no_activity_link(self):
        data = _valid_post_data(self.province, self.district, self.department)
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse('bookings:my_requests'), fetch_redirect_response=False)
        req = TransportRequest.objects.get()
        self.assertIsNone(req.activity)
        self.assertEqual(req.programme_activity, 'Field Visit')

    def test_user_without_department_blocked(self):
        self.user.department = None
        self.user.save()
        data = _valid_post_data(self.province, self.district, self.department)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no department set')
        self.assertEqual(TransportRequest.objects.count(), 0)
