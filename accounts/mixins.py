from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class SortableListMixin:
    """Add server-side, header-click sorting to a ListView.

    Subclasses define ``sortable_fields`` mapping a short query-param key to the
    underlying ORM field name (or annotation). ``?sort=<key>`` selects the column
    and ``?dir=desc`` flips direction (defaults to ascending). ``default_sort`` is
    used when no valid ``sort`` param is present. The current sort key/direction
    are exposed to the template so headers can render links and arrows.
    """
    sortable_fields = {}
    default_sort = None

    def get_sort_params(self):
        sort = self.request.GET.get('sort')
        if sort not in self.sortable_fields:
            sort = self.default_sort
        direction = 'desc' if self.request.GET.get('dir') == 'desc' else 'asc'
        return sort, direction

    def apply_sort(self, queryset):
        sort, direction = self.get_sort_params()
        if not sort:
            return queryset
        field = self.sortable_fields[sort]
        return queryset.order_by(f'-{field}' if direction == 'desc' else field)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sort, direction = self.get_sort_params()
        context['current_sort'] = sort
        context['current_dir'] = direction
        return context


class GroupRequiredMixin(LoginRequiredMixin):
    """Restrict a class-based view to users in any of the specified groups.

    Set group_required to a string or list of group names on the subclass.
    Unauthenticated users are redirected to LOGIN_URL; wrong-group users get 403.
    """
    group_required = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        # Superusers bypass group checks (parity with ImpTracker's role helpers).
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        groups = self.group_required
        if isinstance(groups, str):
            groups = [groups]
        if not request.user.groups.filter(name__in=groups).exists():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
