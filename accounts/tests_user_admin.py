"""Tests for account-flag handling on the user edit form: is_staff/is_superuser
bypass all role checks, so only superusers may change them, never on themselves."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


def edit_post_data(user, **extra):
    group = Group.objects.get(name='Viewer')
    data = {
        'username': user.username,
        'email': user.email or 'x@example.com',
        'first_name': user.first_name or 'First',
        'last_name': user.last_name or 'Last',
        'is_active': 'on',
        'roles': [str(group.pk)],
    }
    data.update(extra)
    return data


class AccountFlagEditTest(TestCase):

    def setUp(self):
        self.superuser = User.objects.create_superuser(username='root', password='x', email='r@x.com')
        self.staff = User.objects.create_user(username='staffer', password='x', is_staff=True, email='s@x.com')
        self.target = User.objects.create_user(username='bob', password='x', email='b@x.com')

    def edit_url(self, user):
        return reverse('accounts:user_edit', args=[user.pk])

    def test_superuser_can_grant_and_revoke_flags(self):
        self.client.force_login(self.superuser)
        self.client.post(self.edit_url(self.target), edit_post_data(self.target, is_staff='on', is_superuser='on'))
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_staff)
        self.assertTrue(self.target.is_superuser)
        self.client.post(self.edit_url(self.target), edit_post_data(self.target))
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)

    def test_non_superuser_cannot_change_flags(self):
        self.client.force_login(self.staff)
        self.client.post(self.edit_url(self.target), edit_post_data(self.target, is_staff='on', is_superuser='on'))
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)

    def test_superuser_cannot_change_own_flags(self):
        self.client.force_login(self.superuser)
        self.client.post(self.edit_url(self.superuser), edit_post_data(self.superuser))
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_superuser)
        self.assertTrue(self.superuser.is_staff)

    def test_edit_form_warns_about_elevated_account(self):
        elevated = User.objects.create_user(username='boss', password='x', is_staff=True, email='e@x.com')
        self.client.force_login(self.superuser)
        response = self.client.get(self.edit_url(elevated))
        self.assertContains(response, 'bypass role-based permissions')
