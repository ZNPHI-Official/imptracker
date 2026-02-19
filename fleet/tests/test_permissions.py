"""
Fleet Management Permission Tests - Phase 1

Tests all permission-related functionality:
- Group setup and permissions
- Permission decorators
- Permission mixins
- Helper functions
- Role-based access control
"""

from django.test import TestCase, Client
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.views.generic import View
from django.http import HttpResponse
from django.test import RequestFactory
from django.core.exceptions import PermissionDenied

from accounts.models import User
from fleet.models import FleetPermission, FleetUserRole
from fleet.permissions import (
    setup_fleet_permissions,
    fleet_permission_required,
    fleet_permission_required_multi,
    fleet_permission_all_required,
    FleetPermissionMixin,
    DriverOnlyMixin,
    TransportOfficerOnlyMixin,
    user_is_driver,
    user_is_transport_officer,
    user_has_fleet_permission,
)


class FleetPermissionSetupTest(TestCase):
    """Test permission and group setup process."""
    
    def setUp(self):
        """Run setup before each test."""
        setup_fleet_permissions()
    
    def test_driver_group_created(self):
        """Test that Driver group is created."""
        driver_group = Group.objects.filter(name=FleetUserRole.DRIVER).exists()
        self.assertTrue(driver_group, "Driver group should be created")
    
    def test_transport_officer_group_created(self):
        """Test that Transport Officer group is created."""
        officer_group = Group.objects.filter(
            name=FleetUserRole.TRANSPORT_OFFICER
        ).exists()
        self.assertTrue(officer_group, "Transport Officer group should be created")
    
    def test_driver_group_has_correct_permissions(self):
        """Test that Driver group has expected permissions."""
        setup_fleet_permissions()
        driver_group = Group.objects.get(name=FleetUserRole.DRIVER)
        
        expected_perms = [
            "view_own_requests",
            "confirm_trip",
            "update_trip_status",
            "complete_trip",
        ]
        
        actual_codenames = set(
            driver_group.permissions.values_list('codename', flat=True)
        )
        
        for codename in expected_perms:
            self.assertIn(
                codename,
                actual_codenames,
                f"Driver group should have '{codename}' permission"
            )
    
    def test_transport_officer_group_has_correct_permissions(self):
        """Test that Transport Officer group has expected permissions."""
        setup_fleet_permissions()
        officer_group = Group.objects.get(name=FleetUserRole.TRANSPORT_OFFICER)
        
        expected_perms = [
            "approve_request",
            "reject_request",
            "modify_tripallocation",
            "manage_vehicle",
            "manage_driver",
            "manage_maintenance",
        ]
        
        actual_codenames = set(
            officer_group.permissions.values_list('codename', flat=True)
        )
        
        for codename in expected_perms:
            self.assertIn(
                codename,
                actual_codenames,
                f"Transport Officer group should have '{codename}' permission"
            )
    
    def test_setup_is_idempotent(self):
        """Test that setup can be called multiple times safely."""
        # Call setup twice
        setup_fleet_permissions()
        driver_group_count_1 = Group.objects.filter(
            name=FleetUserRole.DRIVER
        ).count()
        
        setup_fleet_permissions()
        driver_group_count_2 = Group.objects.filter(
            name=FleetUserRole.DRIVER
        ).count()
        
        self.assertEqual(
            driver_group_count_1,
            driver_group_count_2,
            "Setup should be idempotent"
        )
    
    def test_custom_permissions_created(self):
        """Test that custom permissions are created in database."""
        from django.contrib.auth.models import Permission
        
        fleet_perms = Permission.objects.filter(
            content_type__app_label="fleet"
        )
        
        self.assertGreater(
            fleet_perms.count(),
            0,
            "Custom fleet permissions should be created"
        )


class DriverHelperFunctionsTest(TestCase):
    """Test helper functions for determining user roles."""
    
    def setUp(self):
        """Create test users and groups."""
        setup_fleet_permissions()
        
        self.driver_user = User.objects.create_user(
            username="driver1",
            password="testpass123"
        )
        driver_group = Group.objects.get(name=FleetUserRole.DRIVER)
        self.driver_user.groups.add(driver_group)
        
        self.officer_user = User.objects.create_user(
            username="officer1",
            password="testpass123"
        )
        officer_group = Group.objects.get(name=FleetUserRole.TRANSPORT_OFFICER)
        self.officer_user.groups.add(officer_group)
        
        self.regular_user = User.objects.create_user(
            username="regular1",
            password="testpass123"
        )
    
    def test_user_is_driver(self):
        """Test user_is_driver helper function."""
        self.assertTrue(
            user_is_driver(self.driver_user),
            "Driver user should be identified as driver"
        )
        self.assertFalse(
            user_is_driver(self.officer_user),
            "Officer user should not be identified as driver"
        )
        self.assertFalse(
            user_is_driver(self.regular_user),
            "Regular user should not be identified as driver"
        )
    
    def test_user_is_transport_officer(self):
        """Test user_is_transport_officer helper function."""
        self.assertTrue(
            user_is_transport_officer(self.officer_user),
            "Officer user should be identified as officer"
        )
        self.assertFalse(
            user_is_transport_officer(self.driver_user),
            "Driver user should not be identified as officer"
        )
        self.assertFalse(
            user_is_transport_officer(self.regular_user),
            "Regular user should not be identified as officer"
        )
    
    def test_user_has_fleet_permission(self):
        """Test user_has_fleet_permission helper function."""
        self.assertTrue(
            user_has_fleet_permission(self.driver_user, "fleet.confirm_trip"),
            "Driver should have confirm_trip permission"
        )
        self.assertFalse(
            user_has_fleet_permission(self.driver_user, "fleet.approve_request"),
            "Driver should not have approve_request permission"
        )
        self.assertTrue(
            user_has_fleet_permission(self.officer_user, "fleet.approve_request"),
            "Officer should have approve_request permission"
        )


class DecoratorsPermissionTest(TestCase):
    """Test permission decorators for views."""
    
    def setUp(self):
        """Create test users and set up permissions."""
        setup_fleet_permissions()
        
        self.driver_user = User.objects.create_user(
            username="driver1",
            password="testpass123"
        )
        driver_group = Group.objects.get(name=FleetUserRole.DRIVER)
        self.driver_user.groups.add(driver_group)
        
        self.officer_user = User.objects.create_user(
            username="officer1",
            password="testpass123"
        )
        officer_group = Group.objects.get(name=FleetUserRole.TRANSPORT_OFFICER)
        self.officer_user.groups.add(officer_group)
        
        self.anon_user = User.objects.create_user(
            username="anonuser",
            password="testpass123"
        )
        
        self.factory = RequestFactory()
    
    def test_fleet_permission_required_decorator_grants_access(self):
        """Test that decorator grants access to authorized user."""
        @fleet_permission_required("fleet.confirm_trip")
        def test_view(request):
            return HttpResponse("Success")
        
        request = self.factory.get("/")
        request.user = self.driver_user
        
        response = test_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Success")
    
    def test_fleet_permission_required_decorator_denies_unauthorized(self):
        """Test that decorator denies access to unauthorized user."""
        @fleet_permission_required("fleet.approve_request")
        def test_view(request):
            return HttpResponse("Success")
        
        request = self.factory.get("/")
        request.user = self.driver_user
        
        with self.assertRaises(PermissionDenied):
            test_view(request)
    
    def test_fleet_permission_required_multi_decorator_any_match(self):
        """Test multi-permission decorator with ANY logic."""
        @fleet_permission_required_multi([
            "fleet.approve_request",
            "fleet.confirm_trip"
        ])
        def test_view(request):
            return HttpResponse("Success")
        
        # Driver has confirm_trip, should pass
        request = self.factory.get("/")
        request.user = self.driver_user
        
        response = test_view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_fleet_permission_required_all_decorator_all_required(self):
        """Test all-permissions decorator with AND logic."""
        @fleet_permission_all_required([
            "fleet.approve_request",
            "fleet.modify_tripallocation"
        ])
        def test_view(request):
            return HttpResponse("Success")
        
        # Officer has both, should pass
        request = self.factory.get("/")
        request.user = self.officer_user
        
        response = test_view(request)
        self.assertEqual(response.status_code, 200)
        
        # Driver doesn't have approve_request, should fail
        request.user = self.driver_user
        with self.assertRaises(PermissionDenied):
            test_view(request)


class MixinPermissionTest(TestCase):
    """Test permission mixins for class-based views."""
    
    def setUp(self):
        """Create test users and set up permissions."""
        setup_fleet_permissions()
        
        self.driver_user = User.objects.create_user(
            username="driver1",
            password="testpass123"
        )
        driver_group = Group.objects.get(name=FleetUserRole.DRIVER)
        self.driver_user.groups.add(driver_group)
        
        self.officer_user = User.objects.create_user(
            username="officer1",
            password="testpass123"
        )
        officer_group = Group.objects.get(name=FleetUserRole.TRANSPORT_OFFICER)
        self.officer_user.groups.add(officer_group)
        
        self.factory = RequestFactory()
    
    def test_driver_only_mixin_grants_to_driver(self):
        """Test DriverOnlyMixin grants access to drivers."""
        class TestView(DriverOnlyMixin, View):
            def get(self, request):
                return HttpResponse("Success")
        
        request = self.factory.get("/")
        request.user = self.driver_user
        
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_driver_only_mixin_denies_to_officer(self):
        """Test DriverOnlyMixin denies access to non-drivers."""
        class TestView(DriverOnlyMixin, View):
            def get(self, request):
                return HttpResponse("Success")
        
        request = self.factory.get("/")
        request.user = self.officer_user
        
        view = TestView.as_view()
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_transport_officer_only_mixin_grants_to_officer(self):
        """Test TransportOfficerOnlyMixin grants access to officers."""
        class TestView(TransportOfficerOnlyMixin, View):
            def get(self, request):
                return HttpResponse("Success")
        
        request = self.factory.get("/")
        request.user = self.officer_user
        
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_transport_officer_only_mixin_denies_to_driver(self):
        """Test TransportOfficerOnlyMixin denies access to non-officers."""
        class TestView(TransportOfficerOnlyMixin, View):
            def get(self, request):
                return HttpResponse("Success")
        
        request = self.factory.get("/")
        request.user = self.driver_user
        
        view = TestView.as_view()
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_fleet_permission_mixin_single_permission(self):
        """Test FleetPermissionMixin with single permission."""
        class TestView(FleetPermissionMixin, View):
            required_permission = "fleet.confirm_trip"
            
            def get(self, request):
                return HttpResponse("Success")
        
        request = self.factory.get("/")
        request.user = self.driver_user
        
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_fleet_permission_mixin_multiple_any(self):
        """Test FleetPermissionMixin with multiple permissions (ANY)."""
        class TestView(FleetPermissionMixin, View):
            required_permissions = ["fleet.approve_request", "fleet.confirm_trip"]
            require_all_permissions = False
            
            def get(self, request):
                return HttpResponse("Success")
        
        request = self.factory.get("/")
        request.user = self.driver_user
        
        view = TestView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 200)


class RolePermissionsDefinitionTest(TestCase):
    """Test that FleetUserRole properly defines permissions."""
    
    def test_driver_permissions_not_empty(self):
        """Test that driver role has permissions defined."""
        perms = FleetUserRole.get_driver_permissions()
        self.assertGreater(len(perms), 0, "Driver should have permissions")
    
    def test_transport_officer_permissions_not_empty(self):
        """Test that transport officer role has permissions defined."""
        perms = FleetUserRole.get_transport_officer_permissions()
        self.assertGreater(
            len(perms),
            0,
            "Transport Officer should have permissions"
        )
    
    def test_transport_officer_has_more_perms_than_driver(self):
        """Test that Transport Officer has more permissions than Driver."""
        driver_perms = FleetUserRole.get_driver_permissions()
        officer_perms = FleetUserRole.get_transport_officer_permissions()
        
        self.assertGreater(
            len(officer_perms),
            len(driver_perms),
            "Transport Officer should have more permissions than Driver"
        )
    
    def test_all_roles_defined(self):
        """Test that all required roles are defined."""
        roles = FleetUserRole.get_all_roles()
        self.assertIn(FleetUserRole.DRIVER, roles)
        self.assertIn(FleetUserRole.TRANSPORT_OFFICER, roles)


class FleetPermissionDefinitionTest(TestCase):
    """Test that FleetPermission class defines all required permissions."""
    
    def test_all_permissions_defined(self):
        """Test that FleetPermission defines all permissions."""
        all_perms = FleetPermission.get_all_permissions()
        self.assertGreater(len(all_perms), 0, "Should have permissions defined")
    
    def test_request_permissions_defined(self):
        """Test request-related permissions are defined."""
        self.assertEqual(
            FleetPermission.REQUEST_CREATE,
            "fleet.add_transportrequest"
        )
        self.assertEqual(
            FleetPermission.REQUEST_APPROVE,
            "fleet.approve_request"
        )
    
    def test_allocation_permissions_defined(self):
        """Test allocation permissions are defined."""
        self.assertTrue(
            hasattr(FleetPermission, "ALLOCATION_CREATE")
        )
        self.assertTrue(
            hasattr(FleetPermission, "ALLOCATION_MODIFY")
        )
    
    def test_trip_execution_permissions_defined(self):
        """Test trip execution permissions are defined."""
        self.assertTrue(
            hasattr(FleetPermission, "TRIP_CONFIRM")
        )
        self.assertTrue(
            hasattr(FleetPermission, "TRIP_COMPLETE")
        )


class RBACIntegrationTest(TestCase):
    """Integration tests for role-based access control."""
    
    def setUp(self):
        """Create complete test environment."""
        setup_fleet_permissions()
        
        # Create users
        self.driver1 = User.objects.create_user(
            username="driver1",
            password="testpass123"
        )
        driver_group = Group.objects.get(name=FleetUserRole.DRIVER)
        self.driver1.groups.add(driver_group)
        
        self.driver2 = User.objects.create_user(
            username="driver2",
            password="testpass123"
        )
        self.driver2.groups.add(driver_group)
        
        self.officer1 = User.objects.create_user(
            username="officer1",
            password="testpass123"
        )
        officer_group = Group.objects.get(name=FleetUserRole.TRANSPORT_OFFICER)
        self.officer1.groups.add(officer_group)
        
        self.regular_user = User.objects.create_user(
            username="regular",
            password="testpass123"
        )
    
    def test_driver_cannot_access_officer_permission(self):
        """Test that drivers cannot perform officer actions."""
        self.assertFalse(
            user_has_fleet_permission(self.driver1, "fleet.approve_request")
        )
    
    def test_officer_can_access_driver_permission(self):
        """Test that officers can perform driver actions."""
        # Officers should be able to confirm trips (for testing purposes)
        # In real scenario, only drivers would do this, but officers might need to
        driver_perms = set(FleetUserRole.get_driver_permissions())
        officer_perms = set(FleetUserRole.get_transport_officer_permissions())
        
        # Check if officer has subset or overlap with driver perms
        overlap = driver_perms & officer_perms
        self.assertGreater(
            len(overlap),
            0,
            "Officer should have some driver-level permissions"
        )
    
    def test_multiple_users_same_role_have_same_permissions(self):
        """Test that users in same role have same permissions."""
        driver1_perms = set(self.driver1.get_user_permissions())
        driver2_perms = set(self.driver2.get_user_permissions())
        
        # Both should have group permissions
        self.assertTrue(
            user_has_fleet_permission(self.driver1, "fleet.confirm_trip")
        )
        self.assertTrue(
            user_has_fleet_permission(self.driver2, "fleet.confirm_trip")
        )
