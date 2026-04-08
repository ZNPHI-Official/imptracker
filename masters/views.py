from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from .models import (
    Funder,
    ActivityStatus,
    Currency,
    ProcurementType,
    ActivityCategory,
    ActivitySubCategory,
)
from accounts.models import Cluster

def is_data_manager(user):
    """Check if user has Data Manager or System Admin role"""
    return user.is_superuser or user.groups.filter(name__in=['Data Manager', 'System Admin']).exists()

# ============= FUNDER VIEWS =============
@login_required
@user_passes_test(is_data_manager)
def funder_list(request):
    """List all funders"""
    query = request.GET.get('q', '')
    show_inactive = request.GET.get('show_inactive', '')
    
    funders = Funder.objects.all().order_by('name')
    
    if query:
        funders = funders.filter(Q(code__icontains=query) | Q(name__icontains=query))
    
    if not show_inactive:
        funders = funders.filter(active=True)
    
    context = {
        'funders': funders,
        'query': query,
        'show_inactive': show_inactive,
    }
    return render(request, 'masters/funder_list.html', context)

@login_required
@user_passes_test(is_data_manager)
def funder_create(request):
    """Create a new funder"""
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        name = request.POST.get('name', '').strip()
        active = request.POST.get('active') == 'on'
        
        if not code or not name:
            messages.error(request, 'Code and Name are required.')
            return redirect('masters:funder_create')
        
        if Funder.objects.filter(code=code).exists():
            messages.error(request, f'Funder with code "{code}" already exists.')
            return redirect('masters:funder_create')
        
        Funder.objects.create(code=code, name=name, active=active)
        messages.success(request, f'Funder "{name}" created successfully.')
        return redirect('masters:funder_list')
    
    return render(request, 'masters/funder_form.html')

@login_required
@user_passes_test(is_data_manager)
def funder_edit(request, pk):
    """Edit an existing funder"""
    funder = get_object_or_404(Funder, pk=pk)
    
    if request.method == 'POST':
        funder.code = request.POST.get('code', '').strip()
        funder.name = request.POST.get('name', '').strip()
        funder.active = request.POST.get('active') == 'on'
        
        if not funder.code or not funder.name:
            messages.error(request, 'Code and Name are required.')
            return redirect('masters:funder_edit', pk=pk)
        
        funder.save()
        messages.success(request, f'Funder "{funder.name}" updated successfully.')
        return redirect('masters:funder_list')
    
    context = {'funder': funder, 'is_edit': True}
    return render(request, 'masters/funder_form.html', context)

@login_required
@user_passes_test(is_data_manager)
def funder_delete(request, pk):
    """Delete a funder"""
    if request.method == 'POST':
        funder = get_object_or_404(Funder, pk=pk)
        name = funder.name
        funder.delete()
        messages.success(request, f'Funder "{name}" deleted successfully.')
    return redirect('masters:funder_list')

# ============= STATUS VIEWS =============
@login_required
@user_passes_test(is_data_manager)
def status_list(request):
    """List all activity statuses"""
    query = request.GET.get('q', '')
    statuses = ActivityStatus.objects.all().order_by('name')
    
    if query:
        statuses = statuses.filter(name__icontains=query)
    
    context = {'statuses': statuses, 'query': query}
    return render(request, 'masters/status_list.html', context)

@login_required
@user_passes_test(is_data_manager)
def status_create(request):
    """Create a new status"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        is_default = request.POST.get('is_default') == 'on'
        
        if not name:
            messages.error(request, 'Name is required.')
            return redirect('masters:status_create')
        
        # If setting as default, unset other defaults
        if is_default:
            ActivityStatus.objects.filter(is_default=True).update(is_default=False)
        
        ActivityStatus.objects.create(name=name, is_default=is_default)
        messages.success(request, f'Status "{name}" created successfully.')
        return redirect('masters:status_list')
    
    return render(request, 'masters/status_form.html')

@login_required
@user_passes_test(is_data_manager)
def status_edit(request, pk):
    """Edit an existing status"""
    status = get_object_or_404(ActivityStatus, pk=pk)
    
    if request.method == 'POST':
        status.name = request.POST.get('name', '').strip()
        is_default = request.POST.get('is_default') == 'on'
        
        if not status.name:
            messages.error(request, 'Name is required.')
            return redirect('masters:status_edit', pk=pk)
        
        # If setting as default, unset other defaults
        if is_default and not status.is_default:
            ActivityStatus.objects.exclude(pk=pk).update(is_default=False)
        
        status.is_default = is_default
        status.save()
        messages.success(request, f'Status "{status.name}" updated successfully.')
        return redirect('masters:status_list')
    
    context = {'status': status, 'is_edit': True}
    return render(request, 'masters/status_form.html', context)

@login_required
@user_passes_test(is_data_manager)
def status_delete(request, pk):
    """Delete a status"""
    if request.method == 'POST':
        status = get_object_or_404(ActivityStatus, pk=pk)
        name = status.name
        status.delete()
        messages.success(request, f'Status "{name}" deleted successfully.')
    return redirect('masters:status_list')

# ============= CURRENCY VIEWS =============
@login_required
@user_passes_test(is_data_manager)
def currency_list(request):
    """List all currencies"""
    query = request.GET.get('q', '')
    currencies = Currency.objects.all().order_by('code')
    
    if query:
        currencies = currencies.filter(Q(code__icontains=query) | Q(name__icontains=query))
    
    context = {'currencies': currencies, 'query': query}
    return render(request, 'masters/currency_list.html', context)

@login_required
@user_passes_test(is_data_manager)
def currency_create(request):
    """Create a new currency"""
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        name = request.POST.get('name', '').strip()
        symbol = request.POST.get('symbol', '').strip()
        is_default = request.POST.get('is_default') == 'on'
        
        if not code or not name:
            messages.error(request, 'Code and Name are required.')
            return redirect('masters:currency_create')
        
        if Currency.objects.filter(code=code).exists():
            messages.error(request, f'Currency with code "{code}" already exists.')
            return redirect('masters:currency_create')
        
        # If setting as default, unset other defaults
        if is_default:
            Currency.objects.filter(is_default=True).update(is_default=False)
        
        Currency.objects.create(code=code, name=name, symbol=symbol, is_default=is_default)
        messages.success(request, f'Currency "{code}" created successfully.')
        return redirect('masters:currency_list')
    
    return render(request, 'masters/currency_form.html')

@login_required
@user_passes_test(is_data_manager)
def currency_edit(request, pk):
    """Edit an existing currency"""
    currency = get_object_or_404(Currency, pk=pk)
    
    if request.method == 'POST':
        currency.code = request.POST.get('code', '').strip().upper()
        currency.name = request.POST.get('name', '').strip()
        currency.symbol = request.POST.get('symbol', '').strip()
        is_default = request.POST.get('is_default') == 'on'
        
        if not currency.code or not currency.name:
            messages.error(request, 'Code and Name are required.')
            return redirect('masters:currency_edit', pk=pk)
        
        # If setting as default, unset other defaults
        if is_default and not currency.is_default:
            Currency.objects.exclude(pk=pk).update(is_default=False)
        
        currency.is_default = is_default
        currency.save()
        messages.success(request, f'Currency "{currency.code}" updated successfully.')
        return redirect('masters:currency_list')
    
    context = {'currency': currency, 'is_edit': True}
    return render(request, 'masters/currency_form.html', context)

@login_required
@user_passes_test(is_data_manager)
def currency_delete(request, pk):
    """Delete a currency"""
    if request.method == 'POST':
        currency = get_object_or_404(Currency, pk=pk)
        code = currency.code
        currency.delete()
        messages.success(request, f'Currency "{code}" deleted successfully.')
    return redirect('masters:currency_list')

# ============= CLUSTER VIEWS =============
@login_required
@user_passes_test(is_data_manager)
def cluster_list(request):
    """List all clusters"""
    query = request.GET.get('q', '')
    clusters = Cluster.objects.all().order_by('short_name')
    
    if query:
        clusters = clusters.filter(Q(short_name__icontains=query) | Q(full_name__icontains=query))
    
    context = {'clusters': clusters, 'query': query}
    return render(request, 'masters/cluster_list.html', context)

@login_required
@user_passes_test(is_data_manager)
def cluster_create(request):
    """Create a new cluster"""
    if request.method == 'POST':
        short_name = request.POST.get('short_name', '').strip()
        full_name = request.POST.get('full_name', '').strip()
        
        if not short_name or not full_name:
            messages.error(request, 'Short Name and Full Name are required.')
            return redirect('masters:cluster_create')
        
        if Cluster.objects.filter(short_name=short_name).exists():
            messages.error(request, f'Cluster with short name "{short_name}" already exists.')
            return redirect('masters:cluster_create')
        
        Cluster.objects.create(short_name=short_name, full_name=full_name)
        messages.success(request, f'Cluster "{short_name}" created successfully.')
        return redirect('masters:cluster_list')
    
    return render(request, 'masters/cluster_form.html')

@login_required
@user_passes_test(is_data_manager)
def cluster_edit(request, pk):
    """Edit an existing cluster"""
    cluster = get_object_or_404(Cluster, pk=pk)
    
    if request.method == 'POST':
        cluster.short_name = request.POST.get('short_name', '').strip()
        cluster.full_name = request.POST.get('full_name', '').strip()
        
        if not cluster.short_name or not cluster.full_name:
            messages.error(request, 'Short Name and Full Name are required.')
            return redirect('masters:cluster_edit', pk=pk)
        
        cluster.save()
        messages.success(request, f'Cluster "{cluster.short_name}" updated successfully.')
        return redirect('masters:cluster_list')
    
    context = {'cluster': cluster, 'is_edit': True}
    return render(request, 'masters/cluster_form.html', context)

@login_required
@user_passes_test(is_data_manager)
def cluster_delete(request, pk):
    """Delete a cluster"""
    if request.method == 'POST':
        cluster = get_object_or_404(Cluster, pk=pk)
        short_name = cluster.short_name
        cluster.delete()
        messages.success(request, f'Cluster "{short_name}" deleted successfully.')
    return redirect('masters:cluster_list')


# ============= PROCUREMENT TYPE VIEWS =============
@login_required
@user_passes_test(is_data_manager)
def procurement_type_list(request):
    """List all procurement types"""
    query = request.GET.get('q', '')
    show_inactive = request.GET.get('show_inactive', '')
    
    types = ProcurementType.objects.all().order_by('name')
    
    if query:
        types = types.filter(Q(code__icontains=query) | Q(name__icontains=query))
    
    if not show_inactive:
        types = types.filter(active=True)
    
    context = {
        'types': types,
        'query': query,
        'show_inactive': show_inactive,
    }
    return render(request, 'masters/procurement_type_list.html', context)

@login_required
@user_passes_test(is_data_manager)
def procurement_type_create(request):
    """Create a new procurement type"""
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        name = request.POST.get('name', '').strip()
        active = request.POST.get('active') == 'on'
        is_default = request.POST.get('is_default') == 'on'
        
        if not code or not name:
            messages.error(request, 'Code and Name are required.')
            return redirect('masters:procurement_type_create')
        
        if ProcurementType.objects.filter(code=code).exists():
            messages.error(request, f'Procurement type with code "{code}" already exists.')
            return redirect('masters:procurement_type_create')
        
        # If setting as default, unset other defaults
        if is_default:
            ProcurementType.objects.filter(is_default=True).update(is_default=False)
        
        proc_type = ProcurementType.objects.create(
            code=code,
            name=name,
            active=active,
            is_default=is_default
        )
        messages.success(request, f'Procurement type "{proc_type.name}" created successfully.')
        return redirect('masters:procurement_type_list')
    
    return render(request, 'masters/procurement_type_form.html')

@login_required
@user_passes_test(is_data_manager)
def procurement_type_edit(request, pk):
    """Edit an existing procurement type"""
    proc_type = get_object_or_404(ProcurementType, pk=pk)
    
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        name = request.POST.get('name', '').strip()
        active = request.POST.get('active') == 'on'
        is_default = request.POST.get('is_default') == 'on'
        
        if not code or not name:
            messages.error(request, 'Code and Name are required.')
            return redirect('masters:procurement_type_edit', pk=pk)
        
        # Check for duplicate code (excluding current)
        if ProcurementType.objects.filter(code=code).exclude(pk=pk).exists():
            messages.error(request, f'Another procurement type with code "{code}" already exists.')
            return redirect('masters:procurement_type_edit', pk=pk)
        
        # If setting as default, unset other defaults
        if is_default:
            ProcurementType.objects.filter(is_default=True).exclude(pk=pk).update(is_default=False)
        
        proc_type.code = code
        proc_type.name = name
        proc_type.active = active
        proc_type.is_default = is_default
        proc_type.save()
        
        messages.success(request, f'Procurement type "{proc_type.name}" updated successfully.')
        return redirect('masters:procurement_type_list')
    
    context = {'proc_type': proc_type, 'is_edit': True}
    return render(request, 'masters/procurement_type_form.html', context)

@login_required
@user_passes_test(is_data_manager)
def procurement_type_delete(request, pk):
    """Delete a procurement type"""
    if request.method == 'POST':
        proc_type = get_object_or_404(ProcurementType, pk=pk)
        name = proc_type.name
        proc_type.delete()
        messages.success(request, f'Procurement type "{name}" deleted successfully.')
    return redirect('masters:procurement_type_list')


# ============= ACTIVITY CATEGORY VIEWS =============
@login_required
@user_passes_test(is_data_manager)
def category_list(request):
    """Manage activity categories and sub categories."""
    categories = ActivityCategory.objects.prefetch_related('sub_categories').order_by('name')
    sub_categories = ActivitySubCategory.objects.select_related('category').order_by('category__name', 'name')

    context = {
        'categories': categories,
        'sub_categories': sub_categories,
    }
    return render(request, 'masters/category_list.html', context)


@login_required
@user_passes_test(is_data_manager)
def category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        active = request.POST.get('active') == 'on'
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

        if not name:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Category name is required.'}, status=400)
            messages.error(request, 'Category name is required.')
            return redirect('masters:category_list')

        if ActivityCategory.objects.filter(name__iexact=name).exists():
            if is_ajax:
                return JsonResponse({'success': False, 'error': f'Category "{name}" already exists.'}, status=400)
            messages.error(request, f'Category "{name}" already exists.')
            return redirect('masters:category_list')

        category = ActivityCategory.objects.create(name=name, active=active)
        if is_ajax:
            return JsonResponse({'success': True, 'id': category.id, 'name': category.name})
        messages.success(request, f'Category "{name}" created successfully.')
    return redirect('masters:category_list')


@login_required
@user_passes_test(is_data_manager)
def sub_category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        category_id = request.POST.get('category', '').strip()
        active = request.POST.get('active') == 'on'
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

        if not name or not category_id:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Sub category name and parent category are required.'}, status=400)
            messages.error(request, 'Sub category name and parent category are required.')
            return redirect('masters:category_list')

        parent = get_object_or_404(ActivityCategory, pk=category_id)

        if ActivitySubCategory.objects.filter(name__iexact=name, category=parent).exists():
            if is_ajax:
                return JsonResponse({'success': False, 'error': f'Sub category "{name}" already exists under "{parent.name}".'}, status=400)
            messages.error(request, f'Sub category "{name}" already exists under "{parent.name}".')
            return redirect('masters:category_list')

        sub_category = ActivitySubCategory.objects.create(name=name, category=parent, active=active)
        if is_ajax:
            return JsonResponse(
                {
                    'success': True,
                    'id': sub_category.id,
                    'name': sub_category.name,
                    'category_id': parent.id,
                    'category_name': parent.name,
                }
            )
        messages.success(request, f'Sub category "{name}" created under "{parent.name}".')
    return redirect('masters:category_list')


@login_required
@user_passes_test(is_data_manager)
def sub_category_move(request, pk):
    if request.method == 'POST':
        sub_category = get_object_or_404(ActivitySubCategory, pk=pk)
        new_category_id = request.POST.get('category', '').strip()
        if not new_category_id:
            messages.error(request, 'Please select a destination category.')
            return redirect('masters:category_list')

        new_category = get_object_or_404(ActivityCategory, pk=new_category_id)
        if ActivitySubCategory.objects.filter(category=new_category, name__iexact=sub_category.name).exclude(pk=sub_category.pk).exists():
            messages.error(
                request,
                f'Sub category "{sub_category.name}" already exists under "{new_category.name}".',
            )
            return redirect('masters:category_list')

        sub_category.category = new_category
        sub_category.save(update_fields=['category'])
        messages.success(request, f'Sub category "{sub_category.name}" moved to "{new_category.name}".')
    return redirect('masters:category_list')


@login_required
@user_passes_test(is_data_manager)
def category_convert_to_sub_category(request, pk):
    """Convert a main category into a sub category of another main category.

    Allowed only when the source category has no existing sub categories.
    """
    if request.method != 'POST':
        return redirect('masters:category_list')

    source_category = get_object_or_404(ActivityCategory, pk=pk)
    target_category_id = request.POST.get('target_category', '').strip()
    if not target_category_id:
        messages.error(request, 'Please select a destination category.')
        return redirect('masters:category_list')

    target_category = get_object_or_404(ActivityCategory, pk=target_category_id)

    if source_category.pk == target_category.pk:
        messages.error(request, 'Source and destination categories must be different.')
        return redirect('masters:category_list')

    if source_category.sub_categories.exists():
        messages.error(
            request,
            f'Cannot convert "{source_category.name}" because it has sub categories. Move/remove them first.',
        )
        return redirect('masters:category_list')

    if ActivitySubCategory.objects.filter(category=target_category, name__iexact=source_category.name).exists():
        messages.error(
            request,
            f'"{target_category.name}" already has a sub category named "{source_category.name}".',
        )
        return redirect('masters:category_list')

    new_sub_category = ActivitySubCategory.objects.create(
        category=target_category,
        name=source_category.name,
        active=source_category.active,
    )

    for activity in source_category.activities.all():
        activity.categories.add(target_category)
        activity.sub_categories.add(new_sub_category)
        activity.categories.remove(source_category)

    source_name = source_category.name
    source_category.delete()
    messages.success(
        request,
        f'Converted "{source_name}" to a sub category under "{target_category.name}".',
    )
    return redirect('masters:category_list')
