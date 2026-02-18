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
from datetime import datetime, timedelta
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
    status = request.GET.get('status')
    cluster = request.GET.get('cluster')
    funder = request.GET.get('funder')
    
    # Build queryset with filters
    qs = Activity.objects.filter(deleted=False)
    
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
    
    if status:
        qs = qs.filter(status__name=status)
    
    if cluster:
        qs = qs.filter(clusters__short_name=cluster)
    
    if funder:
        qs = qs.filter(funders__name=funder)
    
    # First get distinct activities to avoid M2M duplication issues
    distinct_activity_ids = qs.values_list('id', flat=True).distinct()
    qs_distinct = Activity.objects.filter(id__in=distinct_activity_ids)

    # Aggregations
    total_activities = qs_distinct.count()
    by_year = list(qs_distinct.values('year').annotate(total=Count('id')).order_by('year'))
    by_status = list(qs_distinct.values('status__name').annotate(total=Count('id')).filter(status__name__isnull=False))
    by_cluster = list(qs.values('clusters__short_name').annotate(
        total=Count('id', distinct=True),
        total_budget=Sum('total_budget'),
        total_disbursed=Sum('disbursed_amount')
    ).filter(clusters__short_name__isnull=False).order_by('clusters__short_name'))
    by_funder = list(qs.values('funders__name').annotate(
        total=Count('id', distinct=True),
        total_budget=Sum('total_budget')
    ).filter(funders__name__isnull=False).order_by('funders__name'))
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
            for item in activity.procurement_breakdowns:
                total_procurement_value += float(item.get('amount', 0) or 0)
    
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

    funder_labels = [item.get('funders__name') for item in by_funder if item.get('funders__name')]
    funder_counts = [item.get('total') for item in by_funder if item.get('funders__name')]
    funder_budgets = [float(item.get('total_budget') or 0) for item in by_funder if item.get('funders__name')]

    quarter_labels = [f'Q{item.get("quarter")}' for item in by_quarter if item.get("quarter")]
    quarter_counts = [item.get('total') for item in by_quarter if item.get("quarter")]

    month_labels = [f'{item.get("planned_month__year")}-{item.get("planned_month__month"):02d}' for item in by_month if item.get("planned_month__year")]
    month_disbursed = [float(item.get('total_disbursed') or 0) for item in by_month if item.get("planned_month__year")]
    
    # Calculate cumulative disbursement for burn rate
    cumulative_disbursed = []
    cumsum = 0
    for val in month_disbursed:
        cumsum += val
        cumulative_disbursed.append(cumsum)
    
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
        # Chart data for new visualizations
        'activities_by_cluster_data': json.dumps({
            'labels': cluster_labels,
            'series': cluster_counts
        }),
        'budget_by_cluster_data': json.dumps({
            'labels': cluster_labels,
            'budget_series': cluster_budgets,
            'disbursed_series': cluster_disbursed,
            'remaining_series': cluster_remaining
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
            'labels': funder_labels,
            'series': funder_budgets
        }),
        'quarterly_data': json.dumps({
            'labels': quarter_labels,
            'series': quarter_counts
        }),
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
