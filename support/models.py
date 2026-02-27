from django.conf import settings
from django.db import models


class IssueReport(models.Model):
    ISSUE_TYPE_BUG = 'bug'
    ISSUE_TYPE_IMPROVEMENT = 'improvement'

    ISSUE_TYPE_CHOICES = [
        (ISSUE_TYPE_BUG, 'Bug (System issue)'),
        (ISSUE_TYPE_IMPROVEMENT, 'Improvement feature'),
    ]

    STATUS_PENDING_REVIEW = 'pending_review'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_UNDER_REVIEW = 'under_review'
    STATUS_RESOLVED = 'resolved'

    STATUS_CHOICES = [
        (STATUS_PENDING_REVIEW, 'Pending review'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_UNDER_REVIEW, 'Under review'),
        (STATUS_RESOLVED, 'Resolved'),
    ]

    issue_type = models.CharField(max_length=20, choices=ISSUE_TYPE_CHOICES)
    details = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING_REVIEW)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reported_issues')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Issue #{self.pk} - {self.get_issue_type_display()}'
