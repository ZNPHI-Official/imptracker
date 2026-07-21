def user_roles(request):
    """Expose boolean role flags to every template."""
    if not request.user.is_authenticated:
        return {
            'is_requester': False,
            'is_fleet_manager': False,
            'is_dashboard_viewer': False,
            'is_superadmin': False,
        }
    groups = set(request.user.groups.values_list('name', flat=True))
    return {
        'is_requester': 'Requester' in groups,
        'is_fleet_manager': 'Fleet Manager' in groups,
        'is_dashboard_viewer': 'Dashboard Viewer' in groups,
        'is_superadmin': 'Superadmin' in groups or request.user.is_superuser,
    }
