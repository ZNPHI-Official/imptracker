from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def group_required(*group_names):
    """Restrict a view to users belonging to any of the given groups.

    Unauthenticated users are redirected to LOGIN_URL with ?next= preserved.
    Authenticated users outside the groups receive 403 Forbidden.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'{settings.LOGIN_URL}?next={request.path}')
            # Superusers bypass group checks (parity with ImpTracker's role helpers).
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if request.user.groups.filter(name__in=group_names).exists():
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return wrapped
    return decorator
