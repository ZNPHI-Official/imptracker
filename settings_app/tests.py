from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import Settings
User = get_user_model()

SETTINGS_URL = reverse('settings_app:settings')


def _get_or_create_group(name):
    group, _ = Group.objects.get_or_create(name=name)
    return group


def _user_in_group(username, group_name):
    user = User.objects.create_user(username, password='pass')
    user.groups.add(_get_or_create_group(group_name))
    return user


class SettingsSingletonTest(TestCase):
    def test_load_creates_default_row(self):
        self.assertEqual(Settings.objects.count(), 0)
        s = Settings.load()
        self.assertEqual(s.pk, 1)
        self.assertEqual(Settings.objects.count(), 1)

    def test_load_is_idempotent(self):
        Settings.load()
        Settings.load()
        self.assertEqual(Settings.objects.count(), 1)

    def test_save_enforces_singleton(self):
        s1 = Settings.load()
        s1.buffer_days = 3
        s1.save()
        # Create a second instance — should overwrite pk=1, not insert pk=2.
        s2 = Settings(buffer_days=7)
        s2.save()
        self.assertEqual(Settings.objects.count(), 1)
        self.assertEqual(Settings.objects.get(pk=1).buffer_days, 7)

    def test_nudge_window_days_exact(self):
        s = Settings(nudge_mode=Settings.NUDGE_EXACT)
        self.assertEqual(s.nudge_window_days(), 0)

    def test_nudge_window_days_7day(self):
        s = Settings(nudge_mode=Settings.NUDGE_7DAY)
        self.assertEqual(s.nudge_window_days(), 7)

    def test_nudge_window_days_custom(self):
        s = Settings(nudge_mode=Settings.NUDGE_CUSTOM, nudge_custom_days=14)
        self.assertEqual(s.nudge_window_days(), 14)


class SettingsAccessTest(TestCase):
    def test_fleet_manager_gets_200(self):
        user = _user_in_group('fm_user', 'Fleet Manager')
        self.client.force_login(user)
        self.assertEqual(self.client.get(SETTINGS_URL).status_code, 200)

    def test_superadmin_gets_200(self):
        user = _user_in_group('sa_user', 'Superadmin')
        self.client.force_login(user)
        self.assertEqual(self.client.get(SETTINGS_URL).status_code, 200)

    def test_requester_gets_403(self):
        user = _user_in_group('req_user', 'Requester')
        self.client.force_login(user)
        self.assertEqual(self.client.get(SETTINGS_URL).status_code, 403)

    def test_dashboard_viewer_gets_403(self):
        user = _user_in_group('dv_user', 'Dashboard Viewer')
        self.client.force_login(user)
        self.assertEqual(self.client.get(SETTINGS_URL).status_code, 403)

    def test_unauthenticated_redirects(self):
        response = self.client.get(SETTINGS_URL)
        self.assertEqual(response.status_code, 302)


class SettingsFormTest(TestCase):
    def setUp(self):
        self.user = _user_in_group('fm2', 'Fleet Manager')
        self.client.force_login(self.user)

    def _post(self, overrides=None):
        data = {
            'email_notifications_enabled': False,
            'notification_email': '',
            'buffer_days': 1,
            'nudge_mode': '7day',
            'nudge_custom_days': 7,
            'default_maintenance_interval_km': 5000,
        }
        if overrides:
            data.update(overrides)
        return self.client.post(SETTINGS_URL, data)

    def test_valid_post_saves_and_redirects(self):
        response = self._post({'buffer_days': 2, 'default_maintenance_interval_km': 6000})
        self.assertRedirects(response, SETTINGS_URL)
        s = Settings.load()
        self.assertEqual(s.buffer_days, 2)
        self.assertEqual(s.default_maintenance_interval_km, 6000)

    def test_email_settings_saved(self):
        self._post({
            'email_notifications_enabled': True,
            'notification_email': 'fleet@znphi.gov.zm',
        })
        s = Settings.load()
        self.assertTrue(s.email_notifications_enabled)
        self.assertEqual(s.notification_email, 'fleet@znphi.gov.zm')

    def test_custom_nudge_mode_saved(self):
        self._post({'nudge_mode': 'custom', 'nudge_custom_days': 14})
        s = Settings.load()
        self.assertEqual(s.nudge_mode, 'custom')
        self.assertEqual(s.nudge_custom_days, 14)

    def test_invalid_email_shows_error(self):
        response = self._post({
            'email_notifications_enabled': True,
            'notification_email': 'not-an-email',
        })
        self.assertEqual(response.status_code, 200)
        # Django 5.x assertFormError takes the form object directly, not the response.
        self.assertFormError(response.context['form'], 'notification_email', 'Enter a valid email address.')
