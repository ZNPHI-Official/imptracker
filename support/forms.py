from django import forms

from .models import IssueReport


class IssueReportCreateForm(forms.ModelForm):
    class Meta:
        model = IssueReport
        fields = ['issue_type', 'details']
        widgets = {
            'issue_type': forms.Select(attrs={'class': 'form-select'}),
            'details': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Describe the issue or improvement request in detail...'}),
        }


class IssueStatusUpdateForm(forms.ModelForm):
    class Meta:
        model = IssueReport
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        }
