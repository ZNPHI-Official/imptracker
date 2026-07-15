"""Tests for the My Space fleet integration: transport request info per
activity and the quick transport-request modal."""
import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.models import Cluster
from activities.models import Activity
from bookings.models import Department, District, Province, TransportRequest
from masters.models import ActivityStatus

User = get_user_model()


class MySpaceFleetIntegrationTest(TestCase):

    def setUp(self):
        self.cluster = Cluster.objects.create(short_name='SDI', full_name='Surveillance and Disease Intelligence')
        self.user = User.objects.create_user(username='officer', password='x', position='Officer')
        self.user.groups.add(Group.objects.get_or_create(name='Requester')[0])
        self.user.clusters.add(self.cluster)
        self.client.force_login(self.user)

        status = ActivityStatus.objects.create(name='Planned')
        self.activity = Activity.objects.create(
            activity_id='ACT-100', name='Cholera Response', year=2026,
            status=status, planned_month=datetime.date(2026, 8, 1),
            total_budget=5000, responsible_officer=self.user,
        )
        self.province = Province.objects.create(name='Lusaka')
        self.district = District.objects.create(name='Lusaka', province=self.province)
        self.department = Department.objects.create(name='Surveillance and Disease Intelligence')
        self.url = reverse('dashboards:my_space')

    def make_request(self, **kwargs):
        future = datetime.date.today() + datetime.timedelta(weeks=2)
        defaults = dict(
            requester_name='officer', department=self.department, position='Officer',
            programme_activity='ACT-100 — Cholera Response', activity=self.activity,
            period_from=future, period_to=future + datetime.timedelta(days=3),
            province=self.province, district=self.district, destination='Chilenje Clinic',
            submitted_by=self.user,
        )
        defaults.update(kwargs)
        return TransportRequest.objects.create(**defaults)

    def test_fleet_user_sees_transport_section_and_modal(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'My Transport Requests')
        self.assertContains(response, 'transportRequestModal')
        self.assertContains(response, 'ACT-100')  # activity offered in the modal

    def test_activity_row_shows_latest_request_status(self):
        self.make_request(status='Approved')
        response = self.client.get(self.url)
        self.assertContains(response, 'Approved')
        self.assertContains(response, reverse('bookings:request_detail', args=[TransportRequest.objects.get().pk]))

    def test_upcoming_trips_listed(self):
        self.make_request(status='Approved', destination='Kanyama Clinic')
        response = self.client.get(self.url)
        self.assertContains(response, 'Upcoming Trips')
        self.assertContains(response, 'Kanyama Clinic')

    def test_non_fleet_user_gets_no_transport_ui(self):
        user = User.objects.create_user(username='tracker_only', password='x')
        user.groups.add(Group.objects.get_or_create(name='Data Manager')[0])
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'transportRequestModal')
        self.assertNotContains(response, 'My Transport Requests')

    def _existing_requests_map(self, response):
        """Parse the json_script payload the modal reads for duplicate warnings."""
        import json
        content = response.content.decode()
        marker = 'id="existing-requests-data"'
        i = content.find(marker)
        start = content.find('>', i) + 1
        end = content.find('</script>', start)
        return json.loads(content[start:end])

    def test_duplicate_warning_data_for_pending_request(self):
        self.make_request(status='Submitted')
        response = self.client.get(self.url)
        data = self._existing_requests_map(response)
        self.assertIn(str(self.activity.pk), data)
        self.assertEqual(data[str(self.activity.pk)]['status'], 'Submitted')

    def test_duplicate_warning_data_for_approved_request(self):
        self.make_request(status='Approved')
        data = self._existing_requests_map(self.client.get(self.url))
        self.assertEqual(data[str(self.activity.pk)]['status'], 'Approved')

    def test_no_duplicate_data_for_completed_request(self):
        self.make_request(status='Completed')
        data = self._existing_requests_map(self.client.get(self.url))
        self.assertNotIn(str(self.activity.pk), data)

    def test_other_activities_excludes_current_quarter(self):
        import datetime as _dt
        from masters.models import ActivityStatus
        today = _dt.date.today()
        q = (today.month - 1) // 3 + 1
        status = ActivityStatus.objects.get(name='Planned')
        # Activity.save() derives quarter from planned_month, so use real dates:
        # one in the current quarter and one in a different quarter.
        this_q_month = (q - 1) * 3 + 1
        other_q_month = ((q % 4) * 3) + 1  # first month of the next quarter
        self.activity.planned_month = _dt.date(today.year, this_q_month, 1)
        self.activity.year = today.year
        self.activity.save()
        other = Activity.objects.create(
            activity_id='ACT-OTHER', name='Off-quarter work', year=today.year,
            status=status, planned_month=_dt.date(today.year, other_q_month, 1),
            total_budget=100, responsible_officer=self.user,
        )
        response = self.client.get(self.url)
        quarter = response.context['quarter_activities']
        other_list = response.context['other_activities']
        self.assertIn(self.activity, quarter)
        self.assertNotIn(self.activity, other_list)
        self.assertIn(other, other_list)
        self.assertNotIn(other, quarter)
        self.assertContains(response, 'Other Assigned Activities')

    def test_balance_column_subtracts_disbursed(self):
        self.activity.disbursed_amount = 2000
        self.activity.save()
        response = self.client.get(self.url)
        # Balance must be budget - disbursed (3,000), not budget + disbursed (7,000).
        self.assertContains(response, 'K3,000')
        self.assertNotContains(response, 'K7,000')
