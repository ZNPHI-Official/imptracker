"""
Fleet Management Permissions Module

Provides:
1. Permission setup (groups and custom permissions)
2. Decorators for view-level permission enforcement
3. Mixins for class-based views with permission checks
"""

from functools import wraps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import View
from django.db import transaction

from fleet.models import FleetPermission, FleetUserRole


def setup_fleet_permissions():
    """
    Create custom permissions and user groups for fleet management.
    Called automatically when the fleet app is ready.
    
    This function is idempotent - can be called multiple times safely.
    """
    from fleet.models import TransportRequest
    
    # Get or create content type for fleet app permissions
    # Use TransportRequest model as the content type for all custom permissions
    fleet_content_type = ContentType.objects.get(
        app_label="fleet",
        model="transportrequest"
    )
    
    # Define all custom permissions
    permission_definitions = {
        # Request permissions
        "view_own_requests": "Can view own transport requests",
        "view_all_requests": "Can view all transport requests",
        "edit_own_requests": "Can edit own transport requests",
        "cancel_request": "Can cancel transport requests",
        "approve_request": "Can approve transport requests",
        "reject_request": "Can reject transport requests",
        
        # Allocation permissions
        "modify_tripallocation": "Can modify trip allocations",
        
        # Trip execution permissions
        "confirm_trip": "Can confirm trip assignments",
        "update_trip_status": "Can update trip execution status",
        "complete_trip": "Can mark trips as completed",
        
        # Master data permissions
        "manage_vehicle": "Can manage vehicles",
        "manage_driver": "Can manage drivers",
        "manage_maintenance": "Can manage maintenance records",
        
        # Dashboard permissions
        "manage_fleet_dashboard": "Can manage fleet dashboard",
        
        # Audit permissions
        "view_auditlog": "Can view audit logs",
    }
    
    # Create permissions
    for codename, description in permission_definitions.items():
        Permission.objects.get_or_create(
            content_type=fleet_content_type,
            codename=codename,
            defaults={"name": description}
        )
    
    # Create Driver group
    driver_group, _ = Group.objects.get_or_create(name=FleetUserRole.DRIVER)
    driver_permissions = []
    for perm in FleetUserRole.get_driver_permissions():
        try:
            # Extract app_label and codename from permission string
            # e.g., "fleet.view_own_requests" -> ("fleet", "view_own_requests")
            _, codename = perm.split(".")
            permission = Permission.objects.get(
                content_type=fleet_content_type,
                codename=codename
            )
            driver_permissions.append(permission)
        except (Permission.DoesNotExist, ValueError):
            # Silently skip if permission not found
            pass
    
    driver_group.permissions.set(driver_permissions)
    
    # Create Transport Officer group
    officer_group, _ = Group.objects.get_or_create(
        name=FleetUserRole.TRANSPORT_OFFICER
    )
    officer_permissions = []
    for perm in FleetUserRole.get_transport_officer_permissions():
        try:
            _, codename = perm.split(".")
            permission = Permission.objects.get(
                content_type=fleet_content_type,
                codename=codename
            )
            officer_permissions.append(permission)
        except (Permission.DoesNotExist, ValueError):
            pass
    
    officer_group.permissions.set(officer_permissions)


def fleet_permission_required(permission):
    """
    Decorator to require a fleet permission for a view.
    
    Usage:
        @fleet_permission_required("fleet.approve_request")
        def my_view(request):
            ...
    
    Returns 403 Forbidden if user doesn't have permission.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('login')}?next={request.path}")
            
            if not request.user.has_perm(permission):
                raise PermissionDenied(
                    f"You do not have permission: {permission}"
                )
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def fleet_permission_required_multi(permissions):
    """
    Decorator requiring ANY of the provided permissions (OR logic).
    
    Usage:
        @fleet_permission_required_multi([
            "fleet.approve_request",
            "fleet.reject_request"
        ])
        def my_view(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('login')}?next={request.path}")
            
            if not any(request.user.has_perm(perm) for perm in permissions):
                raise PermissionDenied(
                    f"You do not have any of these permissions: {permissions}"
                )
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def fleet_permission_all_required(permissions):
    """
    Decorator requiring ALL provided permissions (AND logic).
    
    Usage:
        @fleet_permission_all_required([
            "fleet.approve_request",
            "fleet.allocate_vehicle"
        ])
        def my_view(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('login')}?next={request.path}")
            
            if not all(request.user.has_perm(perm) for perm in permissions):
                raise PermissionDenied(
                    f"You must have all of these permissions: {permissions}"
                )
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


class FleetPermissionMixin(View):
    """
    Mixin for class-based views requiring fleet permissions.
    
    Define `required_permission` or `required_permissions` on the view class.
    
    Usage:
        class ApproveRequestView(FleetPermissionMixin, UpdateView):
            required_permission = "fleet.approve_request"
    """
    
    required_permission = None
    required_permissions = None  # List of permissions (ANY match)
    require_all_permissions = False  # If True, require ALL permissions
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        
        # Check permissions
        if self.required_permission:
            if not request.user.has_perm(self.required_permission):
                raise PermissionDenied(
                    f"You do not have permission: {self.required_permission}"
                )
        
        elif self.required_permissions:
            if self.require_all_permissions:
                if not all(
                    request.user.has_perm(perm) 
                    for perm in self.required_permissions
                ):
                    raise PermissionDenied(
                        f"You must have all of these permissions: "
                        f"{self.required_permissions}"
                    )
            else:
                if not any(
                    request.user.has_perm(perm) 
                    for perm in self.required_permissions
                ):
                    raise PermissionDenied(
                        f"You do not have any of these permissions: "
                        f"{self.required_permissions}"
                    )
        
        return super().dispatch(request, *args, **kwargs)


class DriverOnlyMixin(FleetPermissionMixin):
    """
    Mixin for views restricted to Drivers.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        
        driver_group = Group.objects.filter(
            name=FleetUserRole.DRIVER,
            user=request.user
        ).exists()
        
        if not driver_group:
            raise PermissionDenied("Only Drivers can access this resource.")
        
        return super(FleetPermissionMixin, self).dispatch(request, *args, **kwargs)


class TransportOfficerOnlyMixin(FleetPermissionMixin):
    """
    Mixin for views restricted to Transport Officers.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        
        officer_group = Group.objects.filter(
            name=FleetUserRole.TRANSPORT_OFFICER,
            user=request.user
        ).exists()
        
        if not officer_group:
            raise PermissionDenied(
                "Only Transport Officers can access this resource."
            )
        
        return super(FleetPermissionMixin, self).dispatch(request, *args, **kwargs)


def user_is_driver(user):
    """
    Helper function to check if user is a driver.
    """
    if not user.is_authenticated:
        return False
    return user.groups.filter(
        name=FleetUserRole.DRIVER
    ).exists()


def user_is_transport_officer(user):
    """
    Helper function to check if user is a transport officer.
    """
    if not user.is_authenticated:
        return False
    return user.groups.filter(
        name=FleetUserRole.TRANSPORT_OFFICER
    ).exists()


def user_has_fleet_permission(user, permission):
    """
    Helper function to check if user has a specific fleet permission.
    """
    if not user.is_authenticated:
        return False
    return user.has_perm(permission)
