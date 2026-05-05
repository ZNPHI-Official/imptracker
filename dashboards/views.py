from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.db.models import Sum, Count, Q
from activities.models import Activity
from activities.views import get_user_role_category, apply_role_based_filters
from audit.models import AuditLog
from .models import SavedDashboardView
from io import BytesIO
import json
from datetime import datetime, timedelta, date
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.textlabels import Label


# Permission helper functions
def has_role(user, role_name):
    """Check if user has a specific role or is superuser"""
    return user.is_superuser or user.groups.filter(name=role_name).exists()


def can_view_dashboard(user):
    """Check if user can view dashboard"""
    return any(has_role(user, role) for role in ['System Admin', 'Data Manager', 'Activity Manager', 'Project Coordinator', 'Viewer'])


@login_required
def dashboard(request):
    if not can_view_dashboard(request.user):
        return HttpResponseForbidden("You do not have permission to view the dashboard")
    
    # Get filters from request
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    year = request.GET.get('year')
    quarter = request.GET.get('quarter')
    status = request.GET.get('status')
    cluster = request.GET.get('cluster')
    funder = request.GET.get('funder')
    
    # Build queryset with filters
    qs = Activity.objects.filter(deleted=False)

    # Match activities list default behavior: current year when no year/date filters are provided
    if not year and not start_date and not end_date:
        current_year = date.today().year
        available_years = Activity.objects.filter(deleted=False).values_list('year', flat=True).distinct()
        if current_year in available_years:
            year = str(current_year)
    
    # Apply role-based filtering
    role_category = get_user_role_category(request.user)
    qs = apply_role_based_filters(qs, request.user)
    
    # Apply date filters to planned_month
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            qs = qs.filter(planned_month__gte=start_dt)
        except (ValueError, TypeError):
            pass
    
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
            qs = qs.filter(planned_month__lte=end_dt)
        except (ValueError, TypeError):
            pass
    
    # Apply other filters
    if year:
        try:
            qs = qs.filter(year=int(year))
        except (ValueError, TypeError):
            pass

    if quarter:
        try:
            quarter_value = int(quarter)
            if quarter_value in [1, 2, 3, 4]:
                qs = qs.filter(quarter=quarter_value)
            else:
                quarter = ''
        except (ValueError, TypeError):
            quarter = ''
    
    if status:
        qs = qs.filter(status__name=status)
    
    if cluster:
        qs = qs.filter(clusters__short_name=cluster)
    
    if funder:
        qs = qs.filter(funders__name=funder)
    
    # First get distinct activities to avoid M2M duplication issues
    distinct_activity_ids = qs.values_list('id', flat=True).distinct()
    qs_distinct = Activity.objects.filter(deleted=False, id__in=distinct_activity_ids)

    # Aggregations
    total_activities = qs_distinct.count()
    by_year = list(qs_distinct.values('year').annotate(total=Count('id')).order_by('year'))
    by_status = list(qs_distinct.values('status__name').annotate(total=Count('id')).filter(status__name__isnull=False))
    # Aggregate per-cluster in Python to avoid SQL row multiplication from multiple M2M joins
    _cluster_agg = {}
    for _activity in qs_distinct.prefetch_related('clusters'):
        _budget = float(_activity.total_budget or 0)
        _disbursed = float(_activity.disbursed_amount or 0)
        for _cluster in _activity.clusters.all():
            if _cluster.short_name:
                if _cluster.short_name not in _cluster_agg:
                    _cluster_agg[_cluster.short_name] = {'total': 0, 'total_budget': 0.0, 'total_disbursed': 0.0}
                _cluster_agg[_cluster.short_name]['total'] += 1
                _cluster_agg[_cluster.short_name]['total_budget'] += _budget
                _cluster_agg[_cluster.short_name]['total_disbursed'] += _disbursed
    by_cluster = [
        {'clusters__short_name': name, 'total': data['total'], 'total_budget': data['total_budget'], 'total_disbursed': data['total_disbursed']}
        for name, data in sorted(_cluster_agg.items())
    ]
    # Aggregate per-funder in Python to avoid M2M row multiplication
    _funder_agg = {}
    for _fa in qs_distinct.prefetch_related('funders'):
        _fb = float(_fa.total_budget or 0)
        _fd = float(_fa.disbursed_amount or 0)
        for _f in _fa.funders.all():
            if _f.name:
                if _f.name not in _funder_agg:
                    _funder_agg[_f.name] = {'total': 0, 'total_budget': 0.0, 'total_disbursed': 0.0}
                _funder_agg[_f.name]['total']          += 1
                _funder_agg[_f.name]['total_budget']   += _fb
                _funder_agg[_f.name]['total_disbursed'] += _fd
    by_funder = [
        {'funders__name': name, 'total': d['total'], 'total_budget': d['total_budget'], 'total_disbursed': d['total_disbursed']}
        for name, d in sorted(_funder_agg.items())
    ]
    by_quarter = list(qs_distinct.values('quarter').annotate(total=Count('id')).filter(quarter__isnull=False).order_by('quarter'))
    by_month = list(qs_distinct.values('planned_month__year', 'planned_month__month').annotate(
        total_disbursed=Sum('disbursed_amount')
    ).filter(planned_month__year__isnull=False).order_by('planned_month__year', 'planned_month__month'))
    
    # Procurement statistics
    procurement_full = qs.filter(is_procurement=True).count()
    procurement_partial = qs.filter(has_partial_procurement=True).count()
    procurement_none = qs.filter(is_procurement=False, has_partial_procurement=False).count()
    
    # Count implemented activities (Fully Implemented or Partially Implemented)
    implemented_count = qs.filter(
        Q(status__name__icontains='Fully Implemented') | 
        Q(status__name__icontains='Partially Implemented')
    ).count()
    
    # Count activities with procurements and sum procurement values
    procurement_activities = qs.filter(Q(is_procurement=True) | Q(has_partial_procurement=True))
    procurement_activities_count = procurement_activities.count()
    
    # Sum up procurement breakdown amounts
    total_procurement_value = 0
    for activity in procurement_activities:
        if activity.procurement_breakdowns:
            # for item in activity.procurement_breakdowns:
            #     total_procurement_value += float(item.get('amount', 0) or 0)

            for item in activity.procurement_breakdowns or []:
                try:
                    total_procurement_value += float(item.get('amount', 0) or 0)
                except (TypeError, ValueError):
                    continue
    
    totals = qs.aggregate(total_budget=Sum('total_budget'), total_disbursed=Sum('disbursed_amount'))
    total_budget = float(totals.get('total_budget') or 0)
    total_disbursed = float(totals.get('total_disbursed') or 0)
    total_balance = total_budget - total_disbursed
    
    # Calculate execution rate
    execution_rate = (total_disbursed / total_budget * 100) if total_budget > 0 else 0

    # Prepare JSON payloads for charts
    years = [item.get('year') for item in by_year]
    year_counts = [item.get('total') for item in by_year]

    status_labels = [item.get('status__name') for item in by_status]
    status_counts = [item.get('total') for item in by_status]

    cluster_labels = [item.get('clusters__short_name') for item in by_cluster if item.get('clusters__short_name')]
    cluster_counts = [item.get('total') for item in by_cluster if item.get('clusters__short_name')]
    cluster_budgets = [float(item.get('total_budget') or 0) for item in by_cluster if item.get('clusters__short_name')]
    cluster_disbursed = [float(item.get('total_disbursed') or 0) for item in by_cluster if item.get('clusters__short_name')]
    cluster_remaining = [float((item.get('total_budget') or 0)) - float((item.get('total_disbursed') or 0)) for item in by_cluster if item.get('clusters__short_name')]
    cluster_execution_rates = [
        round(float(item.get('total_disbursed') or 0) / float(item.get('total_budget') or 1) * 100, 1)
        if float(item.get('total_budget') or 0) > 0 else 0
        for item in by_cluster if item.get('clusters__short_name')
    ]

    funder_labels    = [item.get('funders__name') for item in by_funder if item.get('funders__name')]
    funder_counts    = [item.get('total') for item in by_funder if item.get('funders__name')]
    funder_budgets   = [float(item.get('total_budget') or 0) for item in by_funder if item.get('funders__name')]
    funder_disbursed = [float(item.get('total_disbursed') or 0) for item in by_funder if item.get('funders__name')]
    funder_execution_rates = [
        round(float(item.get('total_disbursed') or 0) / float(item.get('total_budget') or 1) * 100, 1)
        if float(item.get('total_budget') or 0) > 0 else 0.0
        for item in by_funder if item.get('funders__name')
    ]

    quarter_labels = [f'Q{item.get("quarter")}' for item in by_quarter if item.get("quarter")]
    quarter_counts = [item.get('total') for item in by_quarter if item.get("quarter")]

    # ---- Activity category / sub-category aggregation --------------------------
    # Fixed ordering matches the master data so colors are always consistent
    _CATEGORIES = ['Technical', 'Capacity building', 'After Action Review', 'Operational Costs', 'Systems Strengthening']
    _TECH_SUBS  = ['Preparedness', 'Prevention', 'Detection', 'Response']
    _OPEX_SUBS  = ['Rent', 'Utilities', 'Salaries', 'Vehicle Service']

    _cat_agg    = {c: {'count': 0, 'budget': 0.0, 'disbursed': 0.0} for c in _CATEGORIES}
    _subcat_agg = {}  # keyed by subcat name, built dynamically

    for _act in qs_distinct.prefetch_related('categories', 'sub_categories'):
        _ab = float(_act.total_budget or 0)
        _ad = float(_act.disbursed_amount or 0)
        for _cat in _act.categories.all():
            _cn = _cat.name
            if _cn not in _cat_agg:
                _cat_agg[_cn] = {'count': 0, 'budget': 0.0, 'disbursed': 0.0}
            _cat_agg[_cn]['count']    += 1
            _cat_agg[_cn]['budget']   += _ab
            _cat_agg[_cn]['disbursed'] += _ad
        for _sc in _act.sub_categories.all():
            _sn = _sc.name
            if _sn not in _subcat_agg:
                _subcat_agg[_sn] = {'count': 0, 'budget': 0.0, 'disbursed': 0.0}
            _subcat_agg[_sn]['count']    += 1
            _subcat_agg[_sn]['budget']   += _ab
            _subcat_agg[_sn]['disbursed'] += _ad

    def _cat_exec(name):
        d = _cat_agg.get(name, {})
        b = d.get('budget', 0)
        return round(d.get('disbursed', 0) / b * 100, 1) if b > 0 else 0.0

    def _sc_exec(name):
        d = _subcat_agg.get(name, {})
        b = d.get('budget', 0)
        return round(d.get('disbursed', 0) / b * 100, 1) if b > 0 else 0.0

    category_activity_data = json.dumps({
        'labels':          _CATEGORIES,
        'counts':          [_cat_agg[c]['count']    for c in _CATEGORIES],
        'budgets':         [_cat_agg[c]['budget']   for c in _CATEGORIES],
        'disbursed':       [_cat_agg[c]['disbursed'] for c in _CATEGORIES],
        'execution_rates': [_cat_exec(c)             for c in _CATEGORIES],
    })

    technical_subcat_data = json.dumps({
        'labels':          _TECH_SUBS,
        'counts':          [_subcat_agg.get(s, {}).get('count', 0)    for s in _TECH_SUBS],
        'budgets':         [_subcat_agg.get(s, {}).get('budget', 0.0) for s in _TECH_SUBS],
        'disbursed':       [_subcat_agg.get(s, {}).get('disbursed', 0.0) for s in _TECH_SUBS],
        'execution_rates': [_sc_exec(s) for s in _TECH_SUBS],
    })

    opex_subcat_data = json.dumps({
        'labels':          _OPEX_SUBS,
        'counts':          [_subcat_agg.get(s, {}).get('count', 0)    for s in _OPEX_SUBS],
        'budgets':         [_subcat_agg.get(s, {}).get('budget', 0.0) for s in _OPEX_SUBS],
        'disbursed':       [_subcat_agg.get(s, {}).get('disbursed', 0.0) for s in _OPEX_SUBS],
        'execution_rates': [_sc_exec(s) for s in _OPEX_SUBS],
    })
    # ---- End category aggregation -----------------------------------------------

    # ---- Planned vs Actual aggregation ------------------------------------------
    from django.db.models import F

    # --- Activities: planned quarter vs actual completion quarter ---
    _pva_plan   = {}   # {quarter_label: count planned}
    _pva_actual = {}   # {quarter_label: count actually completed}
    _pva_ontime = {}   # {quarter_label: completed on or before planned quarter}
    _pva_late   = {}   # {quarter_label: completed after planned quarter}

    for _act in qs_distinct.only('planned_month', 'quarter', 'year', 'actual_completion_date'):
        if _act.planned_month and _act.quarter and _act.year:
            _ql = f'Q{_act.quarter} {_act.year}'
            _pva_plan[_ql] = _pva_plan.get(_ql, 0) + 1

        if _act.actual_completion_date:
            _aq  = ((_act.actual_completion_date.month - 1) // 3) + 1
            _aql = f'Q{_aq} {_act.actual_completion_date.year}'
            _pva_actual[_aql] = _pva_actual.get(_aql, 0) + 1
            # on-time: actual quarter <= planned quarter (same year)
            if _act.planned_month:
                _planned_end = (_act.year, _act.quarter)
                _actual_end  = (_act.actual_completion_date.year, _aq)
                if _actual_end <= _planned_end:
                    _pva_ontime[_aql] = _pva_ontime.get(_aql, 0) + 1
                else:
                    _pva_late[_aql] = _pva_late.get(_aql, 0) + 1

    _pva_quarters = sorted(
        set(list(_pva_plan.keys()) + list(_pva_actual.keys())),
        #key=lambda x: (int(x.split()[1]), int(x[1]))
        key=lambda x: (int(x.split()[1]), int(x.split()[0][1:]))
    )

    activity_planned_vs_actual = json.dumps({
        'quarters': _pva_quarters,
        'planned':  [_pva_plan.get(q, 0)   for q in _pva_quarters],
        'actual':   [_pva_actual.get(q, 0)  for q in _pva_quarters],
        'on_time':  [_pva_ontime.get(q, 0)  for q in _pva_quarters],
        'late':     [_pva_late.get(q, 0)    for q in _pva_quarters],
    })

    # --- Procurement stages: planned count vs actual count, and on-time count ---
    _PROC_STAGE_FIELDS = [
        ('Tendering', 'tendering_date', 'actual_tendering_date'),
        ('Order',     'order_date',     'actual_order_date'),
        ('Delivery',  'delivery_date',  'actual_delivery_date'),
        ('Payment',   'payment_date',   'actual_payment_date'),
    ]
    _ps_planned = []
    _ps_actual  = []
    _ps_ontime  = []
    _ps_late    = []
    for _stage_name, _pf, _af in _PROC_STAGE_FIELDS:
        _ps_planned.append(qs_distinct.filter(**{f'{_pf}__isnull': False}).count())
        _ps_actual.append(qs_distinct.filter(**{f'{_af}__isnull': False}).count())
        _ps_ontime.append(qs_distinct.filter(
            **{f'{_af}__isnull': False, f'{_pf}__isnull': False,
               f'{_af}__lte': F(_pf)}
        ).count())
        _ps_late.append(qs_distinct.filter(
            **{f'{_af}__isnull': False, f'{_pf}__isnull': False,
               f'{_af}__gt': F(_pf)}
        ).count())

    procurement_planned_vs_actual = json.dumps({
        'stages':   ['Tendering', 'Order', 'Delivery', 'Payment'],
        'planned':  _ps_planned,
        'actual':   _ps_actual,
        'on_time':  _ps_ontime,
        'late':     _ps_late,
    })
    # ---- End planned vs actual aggregation --------------------------------------

    # month_labels = [f'{item.get("planned_month__year")}-{item.get("planned_month__month"):02d}' for item in by_month if item.get("planned_month__year")]
    month_labels = []
    for item in by_month:
        year = item.get("planned_month__year")
        month = item.get("planned_month__month")

        if year and month:
            month_labels.append(f"{year}-{int(month):02d}")

    month_disbursed = [float(item.get('total_disbursed') or 0) for item in by_month if item.get("planned_month__year")]
    
    # Calculate cumulative disbursement for burn rate
    cumulative_disbursed = []
    cumsum = 0
    for val in month_disbursed:
        cumsum += val
        cumulative_disbursed.append(cumsum)
    
    # Procurement stage timeline and status aggregation
    _today = date.today()
    _stages = [
        ('Tendering', 'tendering_date', 'actual_tendering_date'),
        ('Order',     'order_date',     'actual_order_date'),
        ('Delivery',  'delivery_date',  'actual_delivery_date'),
        ('Payment',   'payment_date',   'actual_payment_date'),
    ]
    _stage_status = {s[0]: {'completed': 0, 'pending': 0, 'overdue': 0} for s in _stages}
    _quarter_stage_counts = {}  # {quarter_label: {stage_name: count}}

    for _act in qs_distinct.only(
        'tendering_date', 'order_date', 'delivery_date', 'payment_date',
        'actual_tendering_date', 'actual_order_date', 'actual_delivery_date', 'actual_payment_date'
    ):
        for _stage_name, _planned_field, _actual_field in _stages:
            _planned = getattr(_act, _planned_field)
            _actual = getattr(_act, _actual_field)
            if _actual:
                _stage_status[_stage_name]['completed'] += 1
            elif _planned:
                if _planned < _today:
                    _stage_status[_stage_name]['overdue'] += 1
                else:
                    _stage_status[_stage_name]['pending'] += 1
            if _planned:
                _q = ((_planned.month - 1) // 3) + 1
                _qlabel = f'Q{_q} {_planned.year}'
                if _qlabel not in _quarter_stage_counts:
                    _quarter_stage_counts[_qlabel] = {s[0]: 0 for s in _stages}
                _quarter_stage_counts[_qlabel][_stage_name] += 1

    _sorted_quarters = sorted(
        _quarter_stage_counts.keys(),
        # key=lambda x: (int(x.split()[1]), int(x[1]))
        key=lambda x: (int(x.split()[1]), int(x.split()[0][1:]))
    )

    procurement_stage_timeline_data = json.dumps({
        'quarters': _sorted_quarters,
        'tendering': [_quarter_stage_counts[q]['Tendering'] for q in _sorted_quarters],
        'order':     [_quarter_stage_counts[q]['Order']     for q in _sorted_quarters],
        'delivery':  [_quarter_stage_counts[q]['Delivery']  for q in _sorted_quarters],
        'payment':   [_quarter_stage_counts[q]['Payment']   for q in _sorted_quarters],
    })

    procurement_stage_status_data = json.dumps({
        'stages':    [s[0] for s in _stages],
        'completed': [_stage_status[s[0]]['completed'] for s in _stages],
        'pending':   [_stage_status[s[0]]['pending']   for s in _stages],
        'overdue':   [_stage_status[s[0]]['overdue']   for s in _stages],
    })

    # ---- Construction activity aggregations ----------------------------------------
    qs_construction = qs_distinct.filter(is_construction=True)
    construction_total = qs_construction.count()

    # Status distribution
    _const_status_qs = list(
        qs_construction.values('status__name')
        .annotate(n=Count('id'))
        .filter(status__name__isnull=False)
        .order_by('-n')
    )
    const_status_labels = [r['status__name'] for r in _const_status_qs]
    const_status_counts = [r['n'] for r in _const_status_qs]

    # Budget vs disbursed per cluster (Python aggregation — avoids M2M multiplication)
    _const_cluster_agg = {}
    for _ca in qs_construction.prefetch_related('clusters'):
        _cb = float(_ca.total_budget or 0)
        _cd = float(_ca.disbursed_amount or 0)
        for _cl in _ca.clusters.all():
            if _cl.short_name:
                if _cl.short_name not in _const_cluster_agg:
                    _const_cluster_agg[_cl.short_name] = {'budget': 0.0, 'disbursed': 0.0}
                _const_cluster_agg[_cl.short_name]['budget']    += _cb
                _const_cluster_agg[_cl.short_name]['disbursed'] += _cd
    _const_cluster_agg = dict(sorted(_const_cluster_agg.items()))
    const_cluster_labels    = list(_const_cluster_agg.keys())
    const_cluster_budgets   = [v['budget']    for v in _const_cluster_agg.values()]
    const_cluster_disbursed = [v['disbursed'] for v in _const_cluster_agg.values()]
    const_cluster_balance   = [v['budget'] - v['disbursed'] for v in _const_cluster_agg.values()]

    # Quarter × status stacked bar (timeline)
    _all_statuses_for_const = list(dict.fromkeys(const_status_labels))  # ordered, unique
    _const_quarter_status = {}  # {quarter_label: {status_name: count}}
    for _ca in qs_construction.select_related('status'):
        if not _ca.planned_month:
            continue
        _q = ((_ca.planned_month.month - 1) // 3) + 1
        _ql = f'Q{_q} {_ca.planned_month.year}'
        _sn = _ca.status.name if _ca.status else 'Unknown'
        if _ql not in _const_quarter_status:
            _const_quarter_status[_ql] = {}
        _const_quarter_status[_ql][_sn] = _const_quarter_status[_ql].get(_sn, 0) + 1
        if _sn not in _all_statuses_for_const:
            _all_statuses_for_const.append(_sn)
    _const_quarters_sorted = sorted(
        _const_quarter_status.keys(),
        # key=lambda x: (int(x.split()[1]), int(x[1]))
        key=lambda x: (int(x.split()[1]), int(x.split()[0][1:]))
    )

    construction_timeline_data = json.dumps({
        'quarters': _const_quarters_sorted,
        'statuses': _all_statuses_for_const,
        'series': [
            {
                'name': _st,
                'data': [_const_quarter_status.get(_q, {}).get(_st, 0) for _q in _const_quarters_sorted]
            }
            for _st in _all_statuses_for_const
        ]
    })

    construction_cluster_data = json.dumps({
        'labels':    const_cluster_labels,
        'budget':    const_cluster_budgets,
        'disbursed': const_cluster_disbursed,
        'balance':   const_cluster_balance,
    })

    construction_status_data = json.dumps({
        'labels': const_status_labels,
        'series': const_status_counts,
    })
    # ---- End construction aggregations -------------------------------------------

    # Get recent activities (ordered by most recently updated based on audit logs)
    recent_activity_ids = AuditLog.objects.filter(
        activity_id__isnull=False
    ).values('activity_id').distinct().order_by('-timestamp')[:10]
    
    recent_activity_id_list = [item['activity_id'] for item in recent_activity_ids]
    recent_activities = qs.filter(id__in=recent_activity_id_list).select_related('status', 'currency')
    
    # Attach last action to each activity
    for activity in recent_activities:
        last_audit = AuditLog.objects.filter(activity_id=activity.id).select_related('user').first()
        activity.last_action = last_audit
    
    # Count clusters and funders
    total_clusters = qs.values('clusters').distinct().count()
    total_funders = qs.values('funders').distinct().count()

    # Full unfiltered lists for filter dropdowns (always show all options regardless of current filter)
    from accounts.models import Cluster as ClusterModel
    from masters.models import Funder as FunderModel
    all_clusters = list(ClusterModel.objects.values_list('short_name', flat=True).order_by('short_name'))
    all_funders  = list(FunderModel.objects.filter(active=True).values_list('name', flat=True).order_by('name'))

    # Determine chart visibility based on user role and data
    show_cluster_chart = total_clusters > 1 or role_category not in ['coordinator', 'manager']
    show_funder_chart = total_funders > 1 or role_category not in ['coordinator']

    # PDF export of report
    if request.GET.get('export') == 'pdf':
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        # Title
        title = Paragraph("Activity Implementation Report", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 12))

        # Date
        date_str = f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        story.append(Paragraph(date_str, styles['Normal']))
        story.append(Spacer(1, 12))

        # Summary
        summary_text = f"""
        <b>Summary:</b><br/>
        Total Activities: {total_activities}<br/>
        Total Budget: ZMW {total_budget:,.0f}<br/>
        Total Disbursed: ZMW {total_disbursed:,.0f}<br/>
        Balance: ZMW {total_balance:,.0f}<br/>
        Completion Rate: { (total_disbursed / total_budget * 100) if total_budget > 0 else 0 :.1f}%
        """
        story.append(Paragraph(summary_text, styles['Normal']))
        story.append(Spacer(1, 12))

        # Descriptive text
        desc = """
        This report provides insights into the performance and implementation of activities. 
        The completion rate indicates the percentage of budgeted funds that have been disbursed. 
        Activities are distributed across various clusters and funded by different organizations. 
        The burn rate chart shows monthly disbursements, helping track spending velocity. 
        Use this report to monitor progress and identify areas needing attention.
        """
        story.append(Paragraph(desc, styles['Normal']))
        story.append(Spacer(1, 12))

        # Charts
        # Bar chart for Activities by Year
        drawing_year = Drawing(400, 200)
        bc = VerticalBarChart()
        bc.x = 50
        bc.y = 50
        bc.height = 125
        bc.width = 300
        bc.data = [year_counts]
        bc.categoryAxis.categoryNames = [str(y) for y in years]
        bc.valueAxis.valueMin = 0
        bc.bars[0].fillColor = colors.blue
        drawing_year.add(bc)
        story.append(Paragraph("Activities by Year", styles['Heading2']))
        story.append(drawing_year)
        story.append(Spacer(1, 12))

        # Pie chart for Activities by Status
        drawing_status = Drawing(400, 200)
        pc = Pie()
        pc.x = 150
        pc.y = 50
        pc.width = 100
        pc.height = 100
        pc.data = status_counts
        pc.labels = status_labels
        pc.slices.strokeWidth = 0.5
        pc.slices.strokeColor = colors.black
        drawing_status.add(pc)
        story.append(Paragraph("Activities by Status", styles['Heading2']))
        story.append(drawing_status)
        story.append(Spacer(1, 12))

        # Bar chart for Activities by Quarter
        drawing_quarter = Drawing(400, 200)
        bcq = VerticalBarChart()
        bcq.x = 50
        bcq.y = 50
        bcq.height = 125
        bcq.width = 300
        bcq.data = [quarter_counts]
        bcq.categoryAxis.categoryNames = quarter_labels
        bcq.valueAxis.valueMin = 0
        bcq.bars[0].fillColor = colors.green
        drawing_quarter.add(bcq)
        story.append(Paragraph("Activities by Quarter", styles['Heading2']))
        story.append(drawing_quarter)
        story.append(Spacer(1, 12))

        # Tables
        def create_table(data, headers):
            table_data = [headers] + data
            table = Table(table_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 14),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            return table

        # Activities by Year
        year_data = [[item['year'], item['total']] for item in by_year]
        year_table = create_table(year_data, ['Year', 'Count'])
        story.append(Paragraph("Activities by Year", styles['Heading2']))
        story.append(year_table)
        story.append(Spacer(1, 12))

        # Activities by Status
        status_data = [[item['status__name'], item['total']] for item in by_status]
        status_table = create_table(status_data, ['Status', 'Count'])
        story.append(Paragraph("Activities by Status", styles['Heading2']))
        story.append(status_table)
        story.append(Spacer(1, 12))

        # Activities by Cluster
        cluster_data = [[item['clusters__short_name'], item['total']] for item in by_cluster]
        cluster_table = create_table(cluster_data, ['Cluster', 'Count'])
        story.append(Paragraph("Activities by Cluster", styles['Heading2']))
        story.append(cluster_table)
        story.append(Spacer(1, 12))

        # Activities by Funder
        funder_data = [[item['funders__name'], item['total']] for item in by_funder]
        funder_table = create_table(funder_data, ['Funder', 'Count'])
        story.append(Paragraph("Activities by Funder", styles['Heading2']))
        story.append(funder_table)
        story.append(Spacer(1, 12))

        # Activities by Quarter
        quarter_data = [[f'Q{item["quarter"]}', item['total']] for item in by_quarter]
        quarter_table = create_table(quarter_data, ['Quarter', 'Count'])
        story.append(Paragraph("Activities by Quarter", styles['Heading2']))
        story.append(quarter_table)
        story.append(Spacer(1, 12))

        # Monthly Disbursements
        month_data = [[f'{item["planned_month__year"]}-{item["planned_month__month"]:02d}', f'ZMW {item["total_disbursed"]:,.0f}'] for item in by_month]
        month_table = create_table(month_data, ['Month', 'Disbursed'])
        story.append(Paragraph("Monthly Disbursements (Burn Rate)", styles['Heading2']))
        story.append(month_table)

        doc.build(story)
        buf.seek(0)
        resp = HttpResponse(buf.read(), content_type='application/pdf')
        resp['Content-Disposition'] = 'attachment; filename=activity_implementation_report.pdf'
        return resp

    context = {
        'total_activities': total_activities,
        'total_budget_usd': total_budget,
        'total_clusters': total_clusters,
        'total_funders': total_funders,
        'implemented_count': implemented_count,
        'total_disbursed': total_disbursed,
        'procurement_activities_count': procurement_activities_count,
        'total_procurement_value': total_procurement_value,
        'recent_activities': recent_activities,
        'by_year': by_year,
        'by_status': by_status,
        'by_cluster': by_cluster,
        'by_funder': by_funder,
        'by_quarter': by_quarter,
        'by_month': by_month,
        'total_budget': total_budget,
        'total_disbursed': total_disbursed,
        'total_balance': total_balance,
        'user_role': role_category,
        'show_cluster_chart': show_cluster_chart,
        'show_funder_chart': show_funder_chart,
        'selected_quarter': str(quarter) if quarter else '',
        'selected_cluster': cluster or '',
        'selected_funder':  funder or '',
        'all_clusters': all_clusters,
        'all_funders':  all_funders,
        # Chart data for new visualizations
        'activities_by_cluster_data': json.dumps({
            'labels': cluster_labels,
            'series': cluster_counts
        }),
        'budget_by_cluster_data': json.dumps({
            'labels': cluster_labels,
            'budget_series': cluster_budgets,
            'disbursed_series': cluster_disbursed,
            'remaining_series': cluster_remaining,
            'execution_rate_series': cluster_execution_rates
        }),
        'status_distribution_data': json.dumps({
            'labels': status_labels,
            'series': status_counts
        }),
        'budget_execution_data': json.dumps({
            'execution_rate': round(execution_rate, 1),
            'total_budget': total_budget,
            'total_disbursed': total_disbursed
        }),
        'procurement_data': json.dumps({
            'labels': ['Full Procurement', 'Partial Procurement', 'No Procurement'],
            'series': [procurement_full, procurement_partial, procurement_none]
        }),
        'burn_rate_data': json.dumps({
            'labels': month_labels,
            'series': month_disbursed,
            'cumulative_series': cumulative_disbursed
        }),
        'funding_distribution_data': json.dumps({
            'labels':          funder_labels,
            'series':          funder_budgets,
            'disbursed':       funder_disbursed,
            'execution_rates': funder_execution_rates,
        }),
        'quarterly_data': json.dumps({
            'labels': quarter_labels,
            'series': quarter_counts
        }),
        'procurement_stage_timeline_data': procurement_stage_timeline_data,
        'procurement_stage_status_data': procurement_stage_status_data,
        'activity_planned_vs_actual': activity_planned_vs_actual,
        'procurement_planned_vs_actual': procurement_planned_vs_actual,
        'category_activity_data': category_activity_data,
        'technical_subcat_data': technical_subcat_data,
        'opex_subcat_data': opex_subcat_data,
        'construction_total': construction_total,
        'construction_cluster_data': construction_cluster_data,
        'construction_status_data': construction_status_data,
        'construction_timeline_data': construction_timeline_data,
    }
    context.update({
        'years_json': json.dumps(years),
        'year_counts_json': json.dumps(year_counts),
        'status_labels_json': json.dumps(status_labels),
        'status_counts_json': json.dumps(status_counts),
        'cluster_labels_json': json.dumps(cluster_labels),
        'cluster_counts_json': json.dumps(cluster_counts),
        'funder_labels_json': json.dumps(funder_labels),
        'funder_counts_json': json.dumps(funder_counts),
        'quarter_labels_json': json.dumps(quarter_labels),
        'quarter_counts_json': json.dumps(quarter_counts),
        'month_labels_json': json.dumps(month_labels),
        'month_disbursed_json': json.dumps(month_disbursed),
    })
    return render(request, 'dashboards/overview.html', context)


@login_required
def my_space(request):
    """Personal view of activities assigned to the current user."""
    qs = Activity.objects.filter(deleted=False, responsible_officer=request.user)

    today = date.today()
    current_quarter = ((today.month - 1) // 3) + 1

    aggregates = qs.aggregate(
        total_budget=Sum('total_budget'),
        total_disbursed=Sum('disbursed_amount')
    )
    total_budget = float(aggregates.get('total_budget') or 0)
    total_disbursed = float(aggregates.get('total_disbursed') or 0)
    total_remaining = total_budget - total_disbursed
    coverage_pct = round((total_disbursed / total_budget * 100), 1) if total_budget > 0 else 0

    due_month_qs = qs.filter(planned_month__year=today.year, planned_month__month=today.month)
    due_quarter_qs = qs.filter(year=today.year, quarter=current_quarter)

    def sum_money(qset, field):
        return float(qset.aggregate(total=Sum(field)).get('total') or 0)

    context = {
        'today': today,
        'current_quarter': current_quarter,
        'total_assigned': qs.count(),
        'total_budget': total_budget,
        'total_disbursed': total_disbursed,
        'total_remaining': total_remaining,
        'coverage_pct': coverage_pct,
        'due_month_count': due_month_qs.count(),
        'due_month_budget': sum_money(due_month_qs, 'total_budget'),
        'due_month_disbursed': sum_money(due_month_qs, 'disbursed_amount'),
        'due_quarter_count': due_quarter_qs.count(),
        'due_quarter_budget': sum_money(due_quarter_qs, 'total_budget'),
        'due_quarter_disbursed': sum_money(due_quarter_qs, 'disbursed_amount'),
        'recent_assigned': qs.order_by('planned_month')[:20],
    }

    return render(request, 'dashboards/my_space.html', context)


def save_dashboard(request):
    """Save current dashboard view with filters and display options."""
    if request.method == 'POST' and request.user.is_authenticated:
        # Check permission
        if not can_view_dashboard(request.user):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
        
        try:
            data = json.loads(request.body)
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            is_default = data.get('is_default', False)
            
            if not name:
                return JsonResponse({'success': False, 'error': 'Name is required'})
            
            # Check if name already exists for this user
            existing = SavedDashboardView.objects.filter(user=request.user, name=name).first()
            if existing:
                # Update existing
                saved_view = existing
            else:
                # Create new
                saved_view = SavedDashboardView(user=request.user, name=name)
            
            saved_view.description = description
            saved_view.is_default = is_default
            
            # Extract filters from request data
            saved_view.start_date = data.get('start_date')
            saved_view.end_date = data.get('end_date')
            saved_view.year = data.get('year')
            saved_view.status = data.get('status')
            saved_view.cluster = data.get('cluster')
            saved_view.funder = data.get('funder')
            
            # Extract display options
            saved_view.show_year_chart = data.get('show_year_chart', True)
            saved_view.show_status_chart = data.get('show_status_chart', True)
            saved_view.show_cluster_chart = data.get('show_cluster_chart', True)
            saved_view.show_funder_chart = data.get('show_funder_chart', True)
            saved_view.show_quarter_chart = data.get('show_quarter_chart', True)
            saved_view.show_month_chart = data.get('show_month_chart', True)
            
            saved_view.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Dashboard view saved successfully',
                'view_id': saved_view.id
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)


def load_dashboard(request, view_id):
    """Load a saved dashboard view."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    if not can_view_dashboard(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    try:
        saved_view = get_object_or_404(SavedDashboardView, id=view_id, user=request.user)
        
        return JsonResponse({
            'success': True,
            'view': {
                'id': saved_view.id,
                'name': saved_view.name,
                'description': saved_view.description,
                'start_date': saved_view.start_date.isoformat() if saved_view.start_date else '',
                'end_date': saved_view.end_date.isoformat() if saved_view.end_date else '',
                'year': saved_view.year or '',
                'status': saved_view.status or '',
                'cluster': saved_view.cluster or '',
                'funder': saved_view.funder or '',
                'display_options': {
                    'show_year_chart': saved_view.show_year_chart,
                    'show_status_chart': saved_view.show_status_chart,
                    'show_cluster_chart': saved_view.show_cluster_chart,
                    'show_funder_chart': saved_view.show_funder_chart,
                    'show_quarter_chart': saved_view.show_quarter_chart,
                    'show_month_chart': saved_view.show_month_chart,
                }
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def list_saved_dashboards(request):
    """List all saved dashboard views for the current user."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    if not can_view_dashboard(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    try:
        saved_views = SavedDashboardView.objects.filter(user=request.user).order_by('-updated_at')
        
        views_data = [{
            'id': view.id,
            'name': view.name,
            'description': view.description,
            'created_at': view.created_at.isoformat(),
            'updated_at': view.updated_at.isoformat(),
            'is_default': view.is_default,
        } for view in saved_views]
        
        return JsonResponse({
            'success': True,
            'views': views_data
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def delete_saved_dashboard(request, view_id):
    """Delete a saved dashboard view."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    if not can_view_dashboard(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    try:
        saved_view = get_object_or_404(SavedDashboardView, id=view_id, user=request.user)
        name = saved_view.name
        saved_view.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Dashboard view "{name}" deleted successfully'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
