from django.contrib import admin

from .models import IssueReport


@admin.register(IssueReport)
class IssueReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'issue_type', 'status', 'reported_by', 'created_at')
    list_filter = ('issue_type', 'status', 'created_at')
    search_fields = ('details', 'reported_by__username', 'reported_by__first_name', 'reported_by__last_name')
    ordering = ('-created_at',)
