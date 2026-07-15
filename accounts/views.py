from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from .models import User, Cluster
import json

from services.notifications import send_user_created_notification

# Group names that grant access to each application on the post-login switcher.
FLEET_GROUPS = ['Requester', 'Fleet Manager', 'Dashboard Viewer', 'Superadmin']
TRACKER_GROUPS = ['System Admin', 'Data Manager', 'Activity Manager', 'Project Coordinator', 'Viewer', 'User Manager']


def user_has_fleet_access(user):
    """Check if user may enter the Fleet Manager app"""
    return user.is_superuser or user.groups.filter(name__in=FLEET_GROUPS).exists()


def user_has_tracker_access(user):
    """Check if user may enter the Implementation Tracker app"""
    return user.is_superuser or user.groups.filter(name__in=TRACKER_GROUPS).exists()


@login_required
def app_switcher(request):
    """Post-login landing: pick between Implementation Tracker and Fleet Manager.

    Users with access to exactly one app are sent straight into it; users with
    access to both (or neither) see the switcher page.
    """
    has_tracker = user_has_tracker_access(request.user)
    has_fleet = user_has_fleet_access(request.user)
    if has_tracker and not has_fleet:
        return redirect('dashboards:dashboard')
    if has_fleet and not has_tracker:
        return redirect('fleet_home')
    return render(request, 'accounts/app_switcher.html', {
        'has_tracker': has_tracker,
        'has_fleet': has_fleet,
    })


def can_manage_users(user):
    """Check if user can manage users: superuser, staff, or in User Manager/System Admin groups"""
    return user.is_superuser or user.is_staff or user.groups.filter(name__in=['User Manager', 'System Admin']).exists()

def can_see_user(viewer, target):
    """Check if viewer can see/manage the target user"""
    if viewer.is_superuser:
        return True
    if viewer.is_staff:
        return not target.is_superuser
    return not (target.is_staff or target.is_superuser)

def is_system_admin(user):
    """Check if user is System Admin"""
    return user.is_superuser or user.groups.filter(name='System Admin').exists()

@login_required
@user_passes_test(can_manage_users)
def user_list(request):
    """List all users with search and filter"""
    query = request.GET.get('q', '')
    role = request.GET.get('role', '')
    cluster = request.GET.get('cluster', '')
    
    users = User.objects.all().prefetch_related('groups', 'clusters', 'coordinated_funder').order_by('username')
    
    # Filter users based on viewer's permissions
    if not request.user.is_superuser:
        if request.user.is_staff:
            users = users.exclude(is_superuser=True)
        else:
            users = users.exclude(Q(is_staff=True) | Q(is_superuser=True))
    
    if query:
        users = users.filter(
            Q(username__icontains=query) | 
            Q(first_name__icontains=query) | 
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )
    
    if role:
        users = users.filter(groups__name=role)
    
    if cluster:
        users = users.filter(clusters__id=cluster)
    
    roles = Group.objects.all().order_by('name')
    clusters = Cluster.objects.all().order_by('short_name')
    
    context = {
        'users': users,
        'roles': roles,
        'clusters': clusters,
        'query': query,
        'selected_role': role,
        'selected_cluster': cluster,
    }
    return render(request, 'accounts/user_list.html', context)

@login_required
@user_passes_test(can_manage_users)
def user_create(request):
    """Create a new user"""
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip()
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        password = request.POST.get('password')
        is_active = request.POST.get('is_active') == 'on'
        
        # Validate
        if User.objects.filter(username=username).exists():
            messages.error(request, f'Username "{username}" already exists.')
            return redirect('accounts:user_create')
        
        if not username:
            messages.error(request, 'Username is required.')
            return redirect('accounts:user_create')

        if not email:
            messages.error(request, 'Email is required.')
            return redirect('accounts:user_create')

        if not first_name:
            messages.error(request, 'First name is required.')
            return redirect('accounts:user_create')

        if not last_name:
            messages.error(request, 'Last name is required.')
            return redirect('accounts:user_create')

        if not password:
            messages.error(request, 'Password is required.')
            return redirect('accounts:user_create')

        role_ids = request.POST.getlist('roles')
        if not role_ids:
            messages.error(request, 'At least one role is required.')
            return redirect('accounts:user_create')
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
            is_active=is_active
        )

        # Notify the user their account was created (non-blocking)
        try:
            send_user_created_notification(user, created_by=request.user)
        except Exception:
            pass
        
        # Assign roles (required)
        user.groups.set(Group.objects.filter(id__in=role_ids))
        
        # Assign clusters
        cluster_ids = request.POST.getlist('clusters')
        if cluster_ids:
            user.clusters.set(Cluster.objects.filter(id__in=cluster_ids))
        
        # Assign coordinated funder if Project Coordinator
        funder_id = request.POST.get('coordinated_funder')
        if funder_id and 'Project Coordinator' in [g.name for g in Group.objects.filter(id__in=role_ids)]:
            from masters.models import Funder
            try:
                user.coordinated_funder = Funder.objects.get(id=funder_id)
            except Funder.DoesNotExist:
                pass
        
        user.save()
        
        messages.success(request, f'User "{username}" created successfully.')
        return redirect('accounts:user_list')
    
    roles = Group.objects.all().order_by('name')
    clusters = Cluster.objects.all().order_by('short_name')
    from masters.models import Funder
    funders = Funder.objects.filter(active=True).order_by('name')
    context = {
        'roles': roles,
        'clusters': clusters,
        'funders': funders,
    }
    return render(request, 'accounts/user_form.html', context)

@login_required
@user_passes_test(can_manage_users)
def user_edit(request, pk):
    """Edit an existing user"""
    user = get_object_or_404(User, pk=pk)
    
    if not can_see_user(request.user, user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You do not have permission to manage this user.")
    
    if request.method == 'POST':
        user.username = (request.POST.get('username') or '').strip()
        user.email = (request.POST.get('email') or '').strip()
        user.first_name = (request.POST.get('first_name') or '').strip()
        user.last_name = (request.POST.get('last_name') or '').strip()
        user.is_active = request.POST.get('is_active') == 'on'

        if not user.email:
            messages.error(request, 'Email is required.')
            return redirect('accounts:user_edit', pk=pk)

        if not user.first_name:
            messages.error(request, 'First name is required.')
            return redirect('accounts:user_edit', pk=pk)

        if not user.last_name:
            messages.error(request, 'Last name is required.')
            return redirect('accounts:user_edit', pk=pk)
        
        # Assign roles (required)
        role_ids = request.POST.getlist('roles')
        if not role_ids:
            messages.error(request, 'At least one role is required.')
            return redirect('accounts:user_edit', pk=pk)
        user.groups.set(Group.objects.filter(id__in=role_ids))
        
        # Assign clusters
        cluster_ids = request.POST.getlist('clusters')
        user.clusters.set(Cluster.objects.filter(id__in=cluster_ids))
        
        # Assign coordinated funder if Project Coordinator
        funder_id = request.POST.get('coordinated_funder')
        if funder_id and 'Project Coordinator' in [g.name for g in Group.objects.filter(id__in=role_ids)]:
            from masters.models import Funder
            try:
                user.coordinated_funder = Funder.objects.get(id=funder_id)
            except Funder.DoesNotExist:
                pass
        else:
            user.coordinated_funder = None
        
        user.save()
        
        messages.success(request, f'User "{user.username}" updated successfully.')
        return redirect('accounts:user_list')
    
    roles = Group.objects.all().order_by('name')
    clusters = Cluster.objects.all().order_by('short_name')
    from masters.models import Funder
    funders = Funder.objects.filter(active=True).order_by('name')
    user_role_ids = list(user.groups.values_list('id', flat=True))
    user_cluster_ids = list(user.clusters.values_list('id', flat=True))
    user_coordinated_funder_id = user.coordinated_funder.id if user.coordinated_funder else None
    
    context = {
        'user_obj': user,
        'roles': roles,
        'clusters': clusters,
        'funders': funders,
        'user_role_ids': user_role_ids,
        'user_cluster_ids': user_cluster_ids,
        'user_coordinated_funder_id': user_coordinated_funder_id,
        'is_edit': True,
    }
    return render(request, 'accounts/user_form.html', context)

@login_required
@user_passes_test(can_manage_users)
def user_reset_password(request, pk):
    """Reset user password"""
    if request.method == 'POST':
        user = get_object_or_404(User, pk=pk)
        
        if not can_see_user(request.user, user):
            return JsonResponse({'success': False, 'error': 'You do not have permission to manage this user.'})
        
        new_password = request.POST.get('new_password')
        
        if not new_password:
            return JsonResponse({'success': False, 'error': 'Password is required'})
        
        user.set_password(new_password)
        user.save()
        
        return JsonResponse({'success': True, 'message': f'Password reset for {user.username}'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
@user_passes_test(can_manage_users)
def user_delete(request, pk):
    """Delete a user (or deactivate)"""
    if request.method == 'POST':
        user = get_object_or_404(User, pk=pk)
        
        if not can_see_user(request.user, user):
            messages.error(request, 'You do not have permission to manage this user.')
            return redirect('accounts:user_list')
        
        username = user.username
        
        # Safer to deactivate instead of delete
        user.is_active = False
        user.save()
        
        messages.success(request, f'User "{username}" has been deactivated.')
        return redirect('accounts:user_list')
    
    return redirect('accounts:user_list')


# --------- Group / Role Management (staff or superuser only) ---------
def is_staff_or_superuser(user):
    return user.is_staff or user.is_superuser


@login_required
@user_passes_test(is_staff_or_superuser)
def group_list(request):
    """List all groups (roles)"""
    query = request.GET.get('q', '')
    groups = Group.objects.all().prefetch_related('permissions', 'permissions__content_type').order_by('name')
    if query:
        groups = groups.filter(name__icontains=query)

    context = {'groups': groups, 'query': query}
    return render(request, 'accounts/group_list.html', context)


@login_required
@user_passes_test(is_staff_or_superuser)
def group_create(request):
    """Create a new group/role and assign permissions"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        perm_ids = request.POST.getlist('permissions')

        if not name:
            messages.error(request, 'Name is required.')
            return redirect('accounts:group_create')

        if Group.objects.filter(name=name).exists():
            messages.error(request, f'Role "{name}" already exists.')
            return redirect('accounts:group_create')

        group = Group.objects.create(name=name)
        if perm_ids:
            perms = Permission.objects.filter(id__in=perm_ids)
            group.permissions.set(perms)

        messages.success(request, f'Role "{name}" created.')
        return redirect('accounts:group_list')

    permissions = Permission.objects.select_related('content_type').order_by('content_type__app_label', 'codename')
    context = {'permissions': permissions}
    return render(request, 'accounts/group_form.html', context)


@login_required
@user_passes_test(is_staff_or_superuser)
def group_edit(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        perm_ids = request.POST.getlist('permissions')

        if not name:
            messages.error(request, 'Name is required.')
            return redirect('accounts:group_edit', pk=pk)

        # Prevent changing name to an existing group's name
        if Group.objects.exclude(pk=pk).filter(name=name).exists():
            messages.error(request, 'Another role with that name already exists.')
            return redirect('accounts:group_edit', pk=pk)

        group.name = name
        group.save()
        perms = Permission.objects.filter(id__in=perm_ids)
        group.permissions.set(perms)

        messages.success(request, f'Role "{group.name}" updated.')
        return redirect('accounts:group_list')

    permissions = Permission.objects.select_related('content_type').order_by('content_type__app_label', 'codename')
    group_perm_ids = list(group.permissions.values_list('id', flat=True))
    context = {'group': group, 'permissions': permissions, 'group_perm_ids': group_perm_ids, 'is_edit': True}
    return render(request, 'accounts/group_form.html', context)


@login_required
@user_passes_test(is_staff_or_superuser)
def group_delete(request, pk):
    if request.method == 'POST':
        group = get_object_or_404(Group, pk=pk)
        name = group.name
        group.delete()
        messages.success(request, f'Role "{name}" deleted.')
    return redirect('accounts:group_list')


# ============= PROFILE MANAGEMENT =============
@login_required
def profile_view(request):
    """View logged-in user's profile (read-only)"""
    user = request.user
    context = {'user_obj': user}
    return render(request, 'accounts/profile_view.html', context)


@login_required
def profile_edit(request):
    """Allow logged-in user to edit their own profile"""
    user = request.user
    
    if request.method == 'POST':
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name = request.POST.get('last_name', '').strip()
        user.email = request.POST.get('email', '').strip()
        
        user.save()
        messages.success(request, 'Your profile has been updated successfully.')
        return redirect('accounts:profile_view')
    
    context = {'user_obj': user}
    return render(request, 'accounts/profile_edit.html', context)


@login_required
def change_password(request):
    """Allow logged-in user to change their password"""
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        # Verify current password
        if not request.user.check_password(current_password):
            messages.error(request, 'Current password is incorrect.')
            return redirect('accounts:change_password')
        
        # Validate new password
        if len(new_password) < 8:
            messages.error(request, 'New password must be at least 8 characters long.')
            return redirect('accounts:change_password')
        
        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match.')
            return redirect('accounts:change_password')
        
        # Update password
        request.user.set_password(new_password)
        request.user.save()
        
        # Keep user logged in after password change
        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, request.user)
        
        messages.success(request, 'Your password has been changed successfully.')
        return redirect('dashboards:dashboard')
    
    return render(request, 'accounts/change_password.html')
