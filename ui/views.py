from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from accounts.models import User
from masters.models import (
    Funder,
    ActivityStatus,
    Currency,
    ProcurementType,
    ActivityCategory,
    ActivitySubCategory,
)
from accounts.models import Cluster


def is_system_admin(user):
    return user.is_superuser or user.groups.filter(name='System Admin').exists()


@login_required
@user_passes_test(is_system_admin)
def settings(request):
    """System settings dashboard for master data and user admin."""
    context = {
        'user_count': User.objects.count(),
        'funders_count': Funder.objects.count(),
        'statuses_count': ActivityStatus.objects.count(),
        'currencies_count': Currency.objects.count(),
        'clusters_count': Cluster.objects.count(),
        'procurement_types_count': ProcurementType.objects.count(),
        'categories_count': ActivityCategory.objects.count(),
        'sub_categories_count': ActivitySubCategory.objects.count(),
    }
    return render(request, 'ui/settings.html', context)
