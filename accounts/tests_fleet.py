"""Tests for the fleet-related auth pieces merged from ZNPHI Fleet Manager:
group seeding, GroupRequiredMixin (incl. the superuser bypass added during the
merge), and the post-login app switcher routing."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

# /fleet/settings/ is gated by GroupRequiredMixin with ['Fleet Manager', 'Superadmin']
PROTECTED_URL = '/fleet/settings/'


def make_user(username, password='pass123', group_names=()):
    user = User.objects.create_user(username=username, password=password)
    for name in group_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class FleetGroupCreationTest(TestCase):
    """The four fleet roles must exist after the data migration runs."""

    def test_fleet_groups_exist(self):
        names = set(Group.objects.values_list('name', flat=True))
        expected = {'Requester', 'Fleet Manager', 'Dashboard Viewer', 'Superadmin'}
        self.assertTrue(expected.issubset(names), f'Missing groups: {expected - names}')


class GroupRequiredMixinTest(TestCase):
    """GroupRequiredMixin must block unauthenticated and wrong-role users."""

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(PROTECTED_URL)
        self.assertRedirects(
            response,
            f'/login/?next={PROTECTED_URL}',
            fetch_redirect_response=False,
        )

    def test_wrong_group_gets_403(self):
        user = make_user('req1', group_names=['Requester'])
        self.client.force_login(user)
        response = self.client.get(PROTECTED_URL)
        self.assertEqual(response.status_code, 403)

    def test_correct_group_gets_200(self):
        user = make_user('manager1', group_names=['Fleet Manager'])
        self.client.force_login(user)
        response = self.client.get(PROTECTED_URL)
        self.assertEqual(response.status_code, 200)

    def test_superuser_bypasses_group_check(self):
        user = User.objects.create_superuser(username='root', password='pass123')
        self.client.force_login(user)
        response = self.client.get(PROTECTED_URL)
        self.assertEqual(response.status_code, 200)


class AppSwitcherTest(TestCase):
    """Post-login routing between Implementation Tracker and Fleet Manager."""

    def setUp(self):
        Group.objects.get_or_create(name='Data Manager')
        self.url = reverse('app_switcher')

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(
            response, f'/login/?next={self.url}', fetch_redirect_response=False,
        )

    def test_fleet_only_user_auto_redirects_to_fleet(self):
        user = make_user('req1', group_names=['Requester'])
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('fleet_home'), fetch_redirect_response=False)

    def test_tracker_only_user_auto_redirects_to_dashboard(self):
        user = make_user('dm1', group_names=['Data Manager'])
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(
            response, reverse('dashboards:dashboard'), fetch_redirect_response=False,
        )

    def test_dual_role_user_sees_switcher(self):
        user = make_user('both1', group_names=['Data Manager', 'Requester'])
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Implementation Tracker')
        self.assertContains(response, 'Fleet Manager')

    def test_superuser_sees_switcher(self):
        user = User.objects.create_superuser(username='root', password='pass123')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_ungrouped_user_sees_no_access_message(self):
        user = make_user('nobody')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No application access')


class FleetHomeRoutingTest(TestCase):
    """FleetHomeView should redirect each fleet role to its landing section."""

    def test_fleet_manager_goes_to_queue(self):
        user = make_user('manager1', group_names=['Fleet Manager'])
        self.client.force_login(user)
        response = self.client.get(reverse('fleet_home'))
        self.assertRedirects(response, reverse('bookings:request_queue'), fetch_redirect_response=False)

    def test_requester_goes_to_my_requests(self):
        user = make_user('req1', group_names=['Requester'])
        self.client.force_login(user)
        response = self.client.get(reverse('fleet_home'))
        self.assertRedirects(response, reverse('bookings:my_requests'), fetch_redirect_response=False)

    def test_dashboard_viewer_goes_to_fleet_dashboard(self):
        user = make_user('viewer1', group_names=['Dashboard Viewer'])
        self.client.force_login(user)
        response = self.client.get(reverse('fleet_home'))
        self.assertRedirects(response, reverse('dashboard:dashboard'), fetch_redirect_response=False)

    def test_ungrouped_user_gets_200(self):
        user = make_user('nobody')
        self.client.force_login(user)
        response = self.client.get(reverse('fleet_home'))
        self.assertEqual(response.status_code, 200)
