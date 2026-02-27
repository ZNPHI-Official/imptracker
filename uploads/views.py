from io import BytesIO
import os
import tempfile
from datetime import date
from collections import Counter
import calendar
import logging
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponse
from openpyxl import load_workbook
import pandas as pd
import re

from .models import UploadBatch
from services.excel_templates import generate_template, HEADERS
from masters.models import Funder, ActivityStatus
from accounts.models import Cluster
from activities.models import Activity
from masters.models import Currency
from django.core.exceptions import ValidationError
from audit.models import AuditLog

logger = logging.getLogger(__name__)


@login_required
def download_template(request):
    # If a static template exists in static/, serve it directly. Otherwise generate dynamically.
    static_path = os.path.join(settings.BASE_DIR, 'static', 'activities_template.xlsx')
    if os.path.exists(static_path):
        with open(static_path, 'rb') as fh:
            resp = HttpResponse(fh.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            resp['Content-Disposition'] = 'attachment; filename=activities_template.xlsx'
            return resp

    clusters = list(Cluster.objects.values_list('short_name', flat=True))
    funders = list(Funder.objects.values_list('name', flat=True))
    statuses = list(ActivityStatus.objects.values_list('name', flat=True))

    buf = BytesIO()
    generate_template(buf, clusters, funders, statuses)
    buf.seek(0)
    resp = HttpResponse(buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename=activities_template.xlsx'
    return resp


@login_required
def upload_activities(request):
    context = {'errors': [], 'created': 0, 'summary': None, 'staged_file': None}

    def _read_dataframe(file_path: str, original_name: str):
        fname = original_name.lower()
        try:
            if fname.endswith('.csv'):
                # Try common encodings to handle files saved from Excel/Windows
                encodings = ['utf-8', 'utf-8-sig', 'cp1252', 'latin1']
                last_error = None
                for enc in encodings:
                    try:
                        return pd.read_csv(file_path, encoding=enc)
                    except Exception as e:
                        last_error = e
                        continue
                raise last_error or ValueError('Unsupported CSV encoding.')
            elif fname.endswith(('.xlsx', '.xls')):
                return pd.read_excel(file_path, engine='openpyxl')
            else:
                raise ValueError('Unsupported file format. Please upload CSV or Excel file.')
        except Exception as e:
            raise ValueError(f'Failed to read file: {e}')

    def _is_blank(val):
        # Treat None, NaN, empty strings, and literal 'nan'/'none' as blank
        if val is None:
            return True
        try:
            if isinstance(val, float) and pd.isna(val):
                return True
        except Exception:
            pass
        s = str(val).strip()
        return s == '' or s.lower() in ('nan', 'none')

    def _normalize_text(val):
        if val is None:
            return ''
        # Normalize whitespace and non-breaking spaces
        s = str(val).replace('\u00a0', ' ').strip()
        s = ' '.join(s.split())
        return s

    def _normalize_key(val):
        return _normalize_text(val).lower()
    def _normalize_columns(df: pd.DataFrame):
        # Normalize column names to expected canonical headers
        cols = list(df.columns)
        rename = {}
        for c in cols:
            if not isinstance(c, str):
                continue
            key = c.strip().replace('/', ' ').replace('\n', ' ').strip()
            lk = key.lower()
            if 'cluster' in lk:
                rename[c] = 'Cluster'
            elif 'funder' in lk:
                rename[c] = 'Funder'
            elif 'activity name' in lk or 'activity' == lk:
                rename[c] = 'Activity Name'
            elif 'budget' in lk:
                rename[c] = 'Budget Amount'
            elif 'disburs' in lk:
                rename[c] = 'Disbursed Amount'
            elif 'planned' in lk and 'month' in lk:
                rename[c] = 'Planned Implementation Month'
            elif 'implement' in lk and 'status' in lk:
                rename[c] = 'Implementation Status'
            elif 'key note' in lk or 'notes' in lk:
                rename[c] = 'Key Notes'
            elif 'activity id' in lk or 'activity_id' in lk:
                rename[c] = 'Activity ID'
            elif 'currency' in lk:
                rename[c] = 'Currency'
            elif 'retired' in lk:
                rename[c] = 'Retired'
            elif 'technical' in lk and 'report' in lk:
                rename[c] = 'Technical Report Available'
        if rename:
            df = df.rename(columns=rename)
        return df

    def _parse_planned_month(value):
        """Parse planned month values like 'Aug-26', 'Jun-26', 'Oct-2026', or full dates.
        Returns a python `date` object set to the last day of the month, or None if unparsable.
        """
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        # Try month-year formats first (Aug-26, August-26, Aug-2026)
        import datetime
        try:
            # common short form: Mon-YY or Mon-YYYY
            for fmt in ('%b-%y', '%b-%Y', '%B-%y', '%B-%Y'):
                try:
                    dt = datetime.datetime.strptime(s, fmt)
                    yr = dt.year
                    mon = dt.month
                    last = calendar.monthrange(yr, mon)[1]
                    return datetime.date(yr, mon, last)
                except Exception:
                    continue
        except Exception:
            pass
        # Fallback to pandas flexible parsing
        try:
            ts = pd.to_datetime(s, errors='coerce')
            if pd.isna(ts):
                return None
            # convert to last day of month
            yr = ts.year
            mon = ts.month
            last = calendar.monthrange(yr, mon)[1]
            return date(yr, mon, last)
        except Exception:
            return None

    def _stage_file(uploaded_file):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1])
        for chunk in uploaded_file.chunks():
            tmp.write(chunk)
        tmp.close()
        return tmp.name

    def _summarize(df: pd.DataFrame):
        # Basic counts and numeric sums
        total_rows = len(df)
        budget_sum = 0
        disbursed_sum = 0
        clusters = Counter()
        funders = Counter()
        statuses = Counter()
        years = Counter()
        invalid_dates = 0
        first_date = last_date = None
        duplicates = []
        updates = []
        has_id_column = 'Activity ID' in df.columns or 'activity_id' in df.columns

        status_map = {
            _normalize_key(s.name): s for s in ActivityStatus.objects.all()
        }
        available_statuses = [s.name for s in ActivityStatus.objects.all().order_by('name')]
        default_status = ActivityStatus.objects.filter(name__iexact='Not Implemented').first()
        unknown_statuses = set()
        default_status_missing = False

        unknown_funders = set()
        unknown_clusters = set()
        funder_suggestions = {}
        cluster_suggestions = {}
        for idx, row in df.iterrows():
            row_num = idx + 2
            budget_raw = row.get('Budget Amount')
            disb_raw = row.get('Disbursed Amount')
            cluster_name = row.get('Cluster')
            funder_name = row.get('Funder')
            status_name = row.get('Implementation Status')
            planned = row.get('Planned Implementation Month')
            name = row.get('Activity Name')
            activity_id = row.get('Activity ID') or row.get('activity_id')

            try:
                if not _is_blank(budget_raw):
                    budget_sum += float(str(budget_raw).replace(',', '').strip())
            except Exception:
                pass
            try:
                if not _is_blank(disb_raw):
                    disbursed_sum += float(str(disb_raw).replace(',', '').strip())
            except Exception:
                pass

            # support multiple funders/clusters separated by &, comma, or ;
            if not _is_blank(cluster_name):
                parts = [p.strip() for p in re.split('[,&;]', str(cluster_name)) if p.strip() and not _is_blank(p)]
                for p in parts:
                    clusters[p] += 1
                    # detect unknown clusters
                    if not Cluster.objects.filter(short_name__iexact=p).exists() and not Cluster.objects.filter(full_name__iexact=p).exists():
                        unknown_clusters.add(p)
                        similar = list(Cluster.objects.filter(short_name__icontains=p[:4]).values_list('short_name', flat=True)[:5])
                        if similar:
                            cluster_suggestions[p] = similar
            if not _is_blank(funder_name):
                parts = [p.strip() for p in re.split('[,&;]', str(funder_name)) if p.strip() and not _is_blank(p)]
                for p in parts:
                    funders[p] += 1
                    # detect unknown funders
                    if not Funder.objects.filter(name__iexact=p).exists():
                        unknown_funders.add(p)
                        similar = list(Funder.objects.filter(name__icontains=p[:4]).values_list('name', flat=True)[:5])
                        if similar:
                            funder_suggestions[p] = similar
            if _is_blank(status_name):
                if default_status:
                    statuses[default_status.name] += 1
                else:
                    default_status_missing = True
                    statuses['Not Implemented'] += 1
                    unknown_statuses.add('Not Implemented')
            else:
                normalized_status = _normalize_text(status_name)
                statuses[normalized_status] += 1
                if _normalize_key(normalized_status) not in status_map:
                    unknown_statuses.add(normalized_status)

            parsed_dt = None
            if planned:
                parsed_date = _parse_planned_month(planned)
                if parsed_date:
                    # convert to pandas.Timestamp for consistent comparisons
                    parsed_dt = pd.to_datetime(parsed_date)
                else:
                    invalid_dates += 1
            else:
                invalid_dates += 1

            if parsed_dt is not None:
                y = parsed_dt.year
                years[y] += 1
                if not first_date or parsed_dt < first_date:
                    first_date = parsed_dt
                if not last_date or parsed_dt > last_date:
                    last_date = parsed_dt

            # Check for duplicates or updates
            if activity_id and pd.notna(activity_id):
                # Check if activity ID exists in DB
                existing = Activity.objects.filter(activity_id=str(activity_id).strip(), deleted=False).first()
                if existing:
                    updates.append({
                        'row': row_num,
                        'activity_id': str(activity_id).strip(),
                        'name': name,
                        'existing_name': existing.name,
                        'existing_id': existing.id
                    })
            
            # Always check for duplicates (even if activity_id is present)
            if name and pd.notna(name) and parsed_dt is not None:
                # Check for potential duplicates by exact name + year and matching cluster(s)
                try:
                    year_val = parsed_dt.year
                    similar = Activity.objects.filter(
                        deleted=False,
                        name__iexact=str(name).strip(),
                        year=year_val
                    )

                    # If cluster(s) provided in the upload row, filter similar activities
                    # by any of the listed cluster short names (supports multi-values).
                    if cluster_name and pd.notna(cluster_name):
                        cparts = [p.strip() for p in re.split('[,&;]', str(cluster_name)) if p.strip()]
                        if cparts:
                            similar = similar.filter(clusters__short_name__in=cparts)

                    similar = similar.distinct()
                    if similar.exists():
                        # Skip if already in updates list for this row
                        already_in_updates = activity_id and pd.notna(activity_id) and any(
                            u['row'] == row_num for u in updates
                        )
                        if not already_in_updates:
                            for existing in similar[:3]:  # Limit to 3 matches
                                duplicates.append({
                                    'row': row_num,
                                    'name': str(name).strip(),
                                    'existing_id': existing.activity_id,
                                    'existing_name': existing.name,
                                    'existing_year': existing.year,
                                    'existing_cluster': existing.clusters.first().short_name if existing.clusters.exists() else ''
                                })
                except Exception:
                    # Ignore duplicate-checking errors to avoid breaking staging
                    pass

        status_checks = [
            {
                'name': status_name,
                'count': count,
                'valid': _normalize_key(status_name) in status_map
            }
            for status_name, count in statuses.most_common()
        ]

        return {
            'total_rows': total_rows,
            'budget_sum': budget_sum,
            'disbursed_sum': disbursed_sum,
            'clusters': clusters.most_common(),
            'funders': funders.most_common(),
            'statuses': statuses.most_common(),
            'status_checks': status_checks,
            'unknown_statuses': sorted(list(unknown_statuses)),
            'available_statuses': available_statuses,
            'default_status_missing': default_status_missing,
            'years': years.most_common(),
            'invalid_dates': invalid_dates,
            'first_date': first_date.strftime('%Y-%m-%d') if first_date else None,
            'last_date': last_date.strftime('%Y-%m-%d') if last_date else None,
            'duplicates': duplicates,
            'updates': updates,
            'has_id_column': has_id_column,
            'unknown_funders': list(unknown_funders),
            'unknown_clusters': list(unknown_clusters),
            'funder_suggestions': funder_suggestions,
            'cluster_suggestions': cluster_suggestions,
            'unknown_funders_details': [
                {'name': p, 'suggestions': funder_suggestions.get(p, [])} for p in list(unknown_funders)
            ],
            'unknown_clusters_details': [
                {'name': p, 'suggestions': cluster_suggestions.get(p, [])} for p in list(unknown_clusters)
            ],
        }

    def _process_dataframe(df: pd.DataFrame, request_user, user_decisions=None, create_funders=None, create_clusters=None):
        created = 0
        updated = 0
        skipped = 0
        errors = []
        user_decisions = user_decisions or {}
        status_map = {
            _normalize_key(s.name): s for s in ActivityStatus.objects.all()
        }
        default_status = ActivityStatus.objects.filter(name__iexact='Not Implemented').first()
        
        for idx, row in df.iterrows():
            row_num = idx + 2
            name = row.get('Activity Name')
            cluster_name = row.get('Cluster')
            funder_name = row.get('Funder')
            planned = row.get('Planned Implementation Month')
            budget = row.get('Budget Amount')
            status_name = row.get('Implementation Status')
            notes = row.get('Key Notes')
            activity_id = row.get('Activity ID') or row.get('activity_id')

            # Skip completely blank rows
            if (_is_blank(name) and _is_blank(planned) and _is_blank(status_name) and 
                _is_blank(budget) and _is_blank(cluster_name) and _is_blank(funder_name)):
                skipped += 1
                continue

            # Check user decision for this row
            decision = user_decisions.get(str(row_num), 'create')
            if decision == 'skip':
                skipped += 1
                continue

            # Mandatory checks
            if not name:
                errors.append(f'Row {row_num}: missing Activity Name')
                logger.warning('Upload row %s skipped: missing Activity Name', row_num)
                continue
            # Budget and disbursed default to 0 if blank
            if _is_blank(budget):
                budget = 0
            if _is_blank(row.get('Disbursed Amount')):
                disbursed = 0

            if _is_blank(status_name):
                if not default_status:
                    activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                    errors.append(
                        f'Row {row_num} ({activity_name}): missing Implementation Status. '
                        'Ask the system admin to add "Not Implemented" status and re-upload.'
                    )
                    logger.warning('Upload row %s skipped: missing Implementation Status and default is missing', row_num)
                    continue
                status = default_status
            else:
                status_name = _normalize_text(status_name)
                status_key = _normalize_key(status_name)
                status = status_map.get(status_key)
                if not status:
                    activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                    errors.append(
                        f'Row {row_num} ({activity_name}): invalid Status "{status_name}". '
                        'Ask the system admin to add this status and re-upload.'
                    )
                    logger.warning('Upload row %s skipped: invalid Status "%s"', row_num, status_name)
                    continue
            # Cluster and Funder may be blank at planning stage; handle gracefully

            # Resolve clusters (support multiple) - skip if blank
            cluster_objs = []
            if not _is_blank(cluster_name):
                parts = [p.strip() for p in re.split('[,&;]', str(cluster_name)) if p.strip() and not _is_blank(p)]
                for p in parts:
                    c = Cluster.objects.filter(short_name__iexact=p).first() or Cluster.objects.filter(full_name__iexact=p).first()
                    if not c:
                        # try to find similar cluster
                        sim = Cluster.objects.filter(short_name__icontains=p[:4]).first()
                        if sim:
                            c = sim
                        elif create_clusters and p in create_clusters:
                            short = ''.join([ch for ch in p.upper() if ch.isalnum()])[:20] or p[:20]
                            c = Cluster.objects.create(short_name=short, full_name=p)
                        else:
                            activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                            errors.append(f'Row {row_num} ({activity_name}): unknown Cluster "{p}" - please confirm creation in the staging view')
                            logger.warning('Upload row %s unknown Cluster "%s"', row_num, p)
                            c = None
                    if c:
                        cluster_objs.append(c)

            # Resolve funders (support multiple) - skip if blank
            funder_objs = []
            if not _is_blank(funder_name):
                fparts = [p.strip() for p in re.split('[,&;]', str(funder_name)) if p.strip() and not _is_blank(p)]
                for p in fparts:
                    f = Funder.objects.filter(name__iexact=p).first()
                    if not f:
                        # try to find a similar funder
                        f_sim = Funder.objects.filter(name__icontains=p[:4]).first()
                        if f_sim:
                            f = f_sim
                        elif create_funders and p in create_funders:
                            # create a new funder with generated code
                            base = ''.join([ch for ch in p.upper() if ch.isalnum()])[:6] or 'FDR'
                            code = base
                            i = 1
                            while Funder.objects.filter(code=code).exists():
                                code = f"{base}{i}"
                                i += 1
                            f = Funder.objects.create(code=code, name=p, active=True)
                        else:
                            activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                            errors.append(f'Row {row_num} ({activity_name}): unknown Funder "{p}" - please confirm creation in the staging view')
                            logger.warning('Upload row %s unknown Funder "%s"', row_num, p)
                            f = None
                    if f:
                        funder_objs.append(f)

            planned_month = None
            if planned:
                parsed = _parse_planned_month(planned)
                if parsed:
                    planned_month = parsed
                else:
                    activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                    errors.append(f'Row {row_num} ({activity_name}): invalid date format for "{planned}"')
                    logger.warning('Upload row %s skipped: invalid date format "%s"', row_num, planned)
                    continue
            if not planned_month:
                activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                errors.append(f'Row {row_num} ({activity_name}): Planned Implementation Month is required')
                logger.warning('Upload row %s skipped: Planned Implementation Month is required', row_num)
                continue

            activity_year = planned_month.year

            total_budget = 0
            try:
                if not _is_blank(budget):
                    budget_str = str(budget).strip().replace(',', '').replace(' ', '')
                    if budget_str in ('', '-'):
                        total_budget = 0
                    else:
                        total_budget = float(budget_str)
                else:
                    total_budget = 0
            except (ValueError, AttributeError):
                activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                errors.append(f'Row {row_num} ({activity_name}): invalid budget amount "{budget}"')
                logger.warning('Upload row %s skipped: invalid budget amount "%s"', row_num, budget)
                continue

            disbursed = row.get('Disbursed Amount')
            disbursed_amount = 0
            try:
                if not _is_blank(disbursed):
                    disb_str = str(disbursed).strip().replace(',', '').replace(' ', '')
                    if disb_str in ('', '-'):
                        disbursed_amount = 0
                    else:
                        disbursed_amount = float(disb_str)
                else:
                    disbursed_amount = 0
            except (ValueError, AttributeError):
                disbursed_amount = 0

            currency_obj = None
            try:
                currency_obj = Currency.objects.first()
                if 'Currency' in row and row.get('Currency'):
                    curval = str(row.get('Currency')).strip()
                    currency_obj = Currency.objects.filter(code__iexact=curval).first() or Currency.objects.filter(name__iexact=curval).first() or currency_obj
            except Exception:
                currency_obj = None

            try:
                # Check if this is an update operation
                existing = None
                if activity_id and pd.notna(activity_id):
                    existing = Activity.objects.filter(activity_id=str(activity_id).strip(), deleted=False).first()
                
                if existing:
                    # Update existing activity
                    existing.name = name
                    existing.status = status
                    existing.planned_month = planned_month
                    existing.total_budget = total_budget
                    existing.disbursed_amount = disbursed_amount
                    existing.currency = currency_obj or existing.currency
                    existing.notes = '' if _is_blank(notes) else str(notes).strip()
                    existing.year = activity_year
                    existing.clean()
                    existing.save()
                    # update m2m relations
                    try:
                        existing.funders.set([f.id for f in funder_objs])
                        existing.clusters.set([c.id for c in cluster_objs])
                    except Exception:
                        pass
                    AuditLog.objects.create(user=request_user, action='Activity updated via upload', object_repr=str(existing))
                    updated += 1
                else:
                    # Create new activity (save first, then set m2m)
                    act = Activity(
                        name=name,
                        status=status,
                        planned_month=planned_month,
                        total_budget=total_budget,
                        disbursed_amount=disbursed_amount,
                        currency=currency_obj,
                        notes='' if _is_blank(notes) else str(notes).strip(),
                        responsible_officer=None,
                        year=activity_year,
                    )
                    act.clean()
                    act.save()
                    try:
                        if funder_objs:
                            act.funders.set([f.id for f in funder_objs])
                        if cluster_objs:
                            act.clusters.set([c.id for c in cluster_objs])
                    except Exception:
                        pass
                    AuditLog.objects.create(user=request_user, action='Activity created via upload', object_repr=str(act))
                    created += 1
            except ValidationError as ve:
                activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                errors.append(f'Row {row_num} ({activity_name}): validation error: {ve.message_dict if hasattr(ve, "message_dict") else ve}')
                logger.exception('Upload row %s validation error', row_num)
            except Exception as e:
                activity_name = _normalize_text(name) if not _is_blank(name) else "No Name"
                errors.append(f'Row {row_num} ({activity_name}): failed to process activity: {e}')
                logger.exception('Upload row %s failed to process activity', row_num)

        return created, updated, skipped, errors

    # Handle staged confirm
    if request.method == 'POST' and request.POST.get('action') == 'confirm':
        staged = request.session.get('upload_staged')
        if not staged:
            context['errors'].append('No staged upload found. Please upload a file first.')
            return render(request, 'uploads/upload.html', context)
        temp_path = staged.get('path')
        original_name = staged.get('name')
        if not temp_path or not os.path.exists(temp_path):
            context['errors'].append('Staged file is missing. Please upload again.')
            request.session.pop('upload_staged', None)
            return render(request, 'uploads/upload.html', context)

        # Collect user decisions for duplicates
        user_decisions = {}
        for key in request.POST:
            if key.startswith('row_'):
                row_num = key.replace('row_', '')
                decision = request.POST.get(key)
                user_decisions[row_num] = decision

        # Collect confirmation for creating unknown masters
        create_funders = request.POST.getlist('create_funder')
        create_clusters = request.POST.getlist('create_cluster')

        keep_staged = False
        try:
            df = _read_dataframe(temp_path, original_name)
            df = _normalize_columns(df)
            summary = _summarize(df)

            if summary.get('unknown_statuses') or summary.get('default_status_missing'):
                context['errors'].append(
                    'Upload blocked: one or more statuses are not in Activity Status. '
                    'Ask the system admin to add the missing statuses and re-upload.'
                )
                context.update({'summary': summary, 'staged_file': original_name})
                keep_staged = True
                return render(request, 'uploads/upload.html', context)

            created, updated, skipped, errors = _process_dataframe(
                df, request.user, user_decisions, create_funders=create_funders, create_clusters=create_clusters
            )
            
            # pick a batch year from most common year or fallback to current
            years = df['Planned Implementation Month'].dropna().apply(lambda x: pd.to_datetime(x, errors='coerce').year)
            year_val = years.mode().iloc[0] if not years.mode().empty else date.today().year
            batch = UploadBatch.objects.create(year=year_val or date.today().year, uploaded_by=request.user, file_name=original_name)
            AuditLog.objects.create(user=request.user, action='Upload finalized', object_repr=str(batch))
            
            # Store success message in session
            from django.contrib import messages
            if created or updated:
                msg_parts = []
                if created:
                    msg_parts.append(f'{created} activities created')
                if updated:
                    msg_parts.append(f'{updated} activities updated')
                if skipped:
                    msg_parts.append(f'{skipped} activities skipped')
                messages.success(request, f'Upload successful! {", ".join(msg_parts)}.')
            
            if errors:
                error_details = "; ".join(errors[:5])  # Show first 5 errors
                if len(errors) > 5:
                    error_details += f"; ... and {len(errors) - 5} more"
                messages.warning(request, f'Upload completed with {len(errors)} error(s): {error_details}')
                logger.warning('Upload completed with %s errors. Sample: %s', len(errors), errors[:10])
        finally:
            if not keep_staged:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
                request.session.pop('upload_staged', None)

        return redirect('activities_list')

    # Stage upload and show summary
    if request.method == 'POST':
        uploaded = request.FILES.get('file')
        if not uploaded:
            context['errors'].append('No file uploaded')
            return render(request, 'uploads/upload.html', context)

        temp_path = _stage_file(uploaded)
        try:
            df = _read_dataframe(temp_path, uploaded.name)
            df = _normalize_columns(df)
            summary = _summarize(df)
        except ValueError as ve:
            context['errors'].append(str(ve))
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
            return render(request, 'uploads/upload.html', context)

        # store staging info in session
        request.session['upload_staged'] = {'path': temp_path, 'name': uploaded.name}
        context.update({'summary': summary, 'staged_file': uploaded.name})
        return render(request, 'uploads/upload.html', context)

    return render(request, 'uploads/upload.html', context)
