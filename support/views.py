from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .forms import IssueReportCreateForm, IssueStatusUpdateForm
from .models import IssueReport


def is_system_admin(user):
    return user.is_superuser or user.groups.filter(name='System Admin').exists()


def can_delete_issue(user):
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.is_staff or user.has_perm('support.delete_issuereport')


@login_required
def support_list(request):
    if request.method == 'POST':
        create_form = IssueReportCreateForm(request.POST)
        if create_form.is_valid():
            issue = create_form.save(commit=False)
            issue.reported_by = request.user
            issue.save()
            messages.success(request, 'Issue submitted successfully.')
            return redirect('support:list')
        messages.error(request, 'Please correct the errors and try again.')
    else:
        create_form = IssueReportCreateForm()

    issues = IssueReport.objects.select_related('reported_by').all()

    context = {
        'issues': issues,
        'create_form': create_form,
        'can_update_status': is_system_admin(request.user),
        'can_delete_issue': can_delete_issue(request.user),
        'status_choices': IssueReport.STATUS_CHOICES,
    }
    return render(request, 'support/list.html', context)


@login_required
def update_issue_status(request, pk):
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid request method')

    if not is_system_admin(request.user):
        return HttpResponseForbidden('You do not have permission to update issue status')

    issue = get_object_or_404(IssueReport, pk=pk)
    form = IssueStatusUpdateForm(request.POST, instance=issue)

    if form.is_valid():
        form.save()
        messages.success(request, f'Issue #{issue.pk} status updated.')
    else:
        messages.error(request, 'Invalid status value.')

    return redirect('support:list')


@login_required
def delete_issue(request, pk):
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid request method')

    if not can_delete_issue(request.user):
        return HttpResponseForbidden('You do not have permission to delete issue reports')

    issue = get_object_or_404(IssueReport, pk=pk)
    issue.delete()
    messages.success(request, f'Issue #{pk} deleted successfully.')
    return redirect('support:list')
