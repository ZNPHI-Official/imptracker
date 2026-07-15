from .models import TransportRequest


def pending_request_count(request):
    """Adds pending_request_count to all template contexts for Fleet Managers and Superadmins."""
    if not request.user.is_authenticated:
        return {}
    if not (
        request.user.is_superuser
        or request.user.groups.filter(name__in=['Fleet Manager', 'Superadmin']).exists()
    ):
        return {}
    return {'pending_request_count': TransportRequest.objects.filter(status='Submitted').count()}
