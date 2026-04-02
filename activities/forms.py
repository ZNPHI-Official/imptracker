from django import forms
from .models import Activity, ActivityAttachment
from masters.models import Funder, ActivityStatus, Currency, ProcurementType
from accounts.models import Cluster, User
from datetime import date


class ActivityForm(forms.ModelForm):
    """Form for creating and editing activities with role-based field restrictions"""

    category = forms.MultipleChoiceField(
        choices=Activity.CATEGORY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Category"
    )
    
    clusters = forms.ModelMultipleChoiceField(
        queryset=Cluster.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Clusters"
    )
    
    funders = forms.ModelMultipleChoiceField(
        queryset=Funder.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Funders"
    )
    
    class Meta:
        model = Activity
        fields = [
            'name', 'category', 'clusters', 'funders', 'status', 
            'planned_month', 'total_budget', 'disbursed_amount', 
            'currency', 'responsible_officer', 'notes',
            # Recurrence fields
            'is_recurring', 'recurrence_pattern', 'recurrence_interval', 'recurrence_end_date',
            # Procurement fields
            'is_procurement', 'procurement_type', 'procurement_amount',
        ]
        widgets = {
            'name': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Activity name/description'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'planned_month': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'total_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00'}),
            'disbursed_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00'}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
            'responsible_officer': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Additional notes'}),
            # Recurrence
            'is_recurring': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'recurrence_pattern': forms.Select(attrs={'class': 'form-select'}),
            'recurrence_interval': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'placeholder': 'Every N periods'}),
            'recurrence_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            # Procurement
            'is_procurement': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'procurement_type': forms.Select(attrs={'class': 'form-select'}),
            'procurement_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00'}),
        }
        labels = {
            'name': 'Activity Name',
            'category': 'Category',
            'status': 'Implementation Status',
            'planned_month': 'Planned Month',
            'total_budget': 'Total Budget',
            'disbursed_amount': 'Disbursed Amount',
            'currency': 'Currency',
            'responsible_officer': 'Responsible Officer',
            'notes': 'Notes',
            # Recurrence
            'is_recurring': 'This is a recurring activity',
            'recurrence_pattern': 'Recurrence Pattern',
            'recurrence_interval': 'Repeat Every (N periods)',
            'recurrence_end_date': 'Stop Recurring After (optional)',
            # Procurement
            'is_procurement': 'This is a procurement',
            'procurement_type': 'Procurement Type',
            'procurement_amount': 'Procurement Amount',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].initial = self.instance.category if self.instance and self.instance.pk else []
        # Filter to only show active procurement types
        self.fields['procurement_type'].queryset = ProcurementType.objects.filter(active=True)
        self.fields['responsible_officer'].queryset = User.objects.filter(is_active=True).distinct().order_by('first_name', 'last_name', 'username')
        # Set default procurement type if one is marked as default
        if not self.instance.pk:  # Only for new activities
            default_type = ProcurementType.objects.filter(is_default=True, active=True).first()
            if default_type:
                self.fields['procurement_type'].initial = default_type

        selected_cluster_ids = []
        if self.is_bound:
            selected_cluster_ids = [cid for cid in self.data.getlist('clusters') if cid]
        elif self.instance.pk:
            selected_cluster_ids = list(self.instance.clusters.values_list('id', flat=True))

        if selected_cluster_ids:
            self.fields['responsible_officer'].queryset = (
                User.objects.filter(is_active=True, clusters__id__in=selected_cluster_ids)
                .distinct()
                .order_by('first_name', 'last_name', 'username')
            )
        else:
            self.fields['responsible_officer'].queryset = User.objects.none()

    def clean(self):
        cleaned_data = super().clean()

        clusters = cleaned_data.get('clusters')
        funders = cleaned_data.get('funders')
        categories = cleaned_data.get('category') or []
        if not clusters:
            self.add_error('clusters', 'Please select at least one cluster.')
        if not funders:
            self.add_error('funders', 'Please select at least one funder.')

        valid_categories = {value for value, _ in Activity.CATEGORY_CHOICES}
        if any(category_value not in valid_categories for category_value in categories):
            self.add_error('category', 'Invalid category selection.')

        # Validate budget amounts
        total_budget = cleaned_data.get('total_budget')
        disbursed_amount = cleaned_data.get('disbursed_amount')
        
        if total_budget is None:
            self.add_error('total_budget', 'Total budget is required.')
            return cleaned_data
        if total_budget < 0:
            self.add_error('total_budget', 'Total budget must be non-negative.')
        if disbursed_amount is not None and disbursed_amount < 0:
            self.add_error('disbursed_amount', 'Disbursed amount must be non-negative.')
        if disbursed_amount is not None and disbursed_amount > total_budget:
            self.add_error('disbursed_amount', 'Disbursed amount cannot exceed total budget.')
        
        # Validate procurement fields
        procurement_amount = cleaned_data.get('procurement_amount')
        is_procurement = cleaned_data.get('is_procurement')
        procurement_type = cleaned_data.get('procurement_type')
        
        if procurement_amount is not None:
            if procurement_amount < 0:
                self.add_error('procurement_amount', "Procurement amount must be non-negative.")
            if total_budget is not None and procurement_amount > total_budget:
                self.add_error('procurement_amount', "Procurement amount cannot exceed total budget.")
            if procurement_amount > 0 and not procurement_type:
                self.add_error('procurement_type', "Procurement type is required when procurement amount is set.")
            if procurement_amount > 0 and not is_procurement:
                self.add_error('is_procurement', "Please mark as a procurement when specifying a procurement amount.")
        
        # Validate recurrence fields
        is_recurring = cleaned_data.get('is_recurring')
        recurrence_pattern = cleaned_data.get('recurrence_pattern')
        recurrence_interval = cleaned_data.get('recurrence_interval')
        
        if is_recurring:
            if not recurrence_pattern:
                self.add_error('recurrence_pattern', "Recurrence pattern is required when recurring is enabled.")
            if recurrence_interval is None or recurrence_interval < 1:
                self.add_error('recurrence_interval', "Recurrence interval must be at least 1.")

        responsible_officer = cleaned_data.get('responsible_officer')
        if responsible_officer and clusters:
            selected_cluster_ids = list(clusters.values_list('id', flat=True))
            if not responsible_officer.clusters.filter(id__in=selected_cluster_ids).exists():
                self.add_error('responsible_officer', 'Responsible officer must belong to at least one selected cluster.')
        
        return cleaned_data


class BulkActionForm(forms.Form):
    """Form for bulk operations on activities"""
    
    ACTION_CHOICES = (
        ('update_status', 'Update Status'),
        ('delete', 'Mark as Deleted'),
        ('assign_officer', 'Assign Officer'),
    )
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Action'
    )
    
    status = forms.ModelChoiceField(
        queryset=ActivityStatus.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='New Status (for status updates)'
    )
    
    responsible_officer = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Responsible Officer (for assignments)'
    )
    
    activity_ids = forms.CharField(
        widget=forms.HiddenInput(),
        label='Selected Activities'
    )


class ActivityAttachmentForm(forms.ModelForm):
    """Form for uploading activity attachments with version control"""
    
    class Meta:
        model = ActivityAttachment
        fields = ['file', 'document_type', 'description']
        widgets = {
            'file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.docx,.doc,.xlsx,.xls',
                'id': 'attachmentFile'
            }),
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': 'Brief description of the document (optional)'
            }),
        }
        labels = {
            'file': 'Select Document (PDF, Word, or Excel)',
            'document_type': 'Document Type',
            'description': 'Description',
        }
    
    def clean_file(self):
        """Validate file type and size"""
        file = self.cleaned_data.get('file')
        
        if file:
            # Check file extension
            import os
            ext = os.path.splitext(file.name)[1].lower()
            allowed_ext = ['.pdf', '.docx', '.doc', '.xlsx', '.xls']
            if ext not in allowed_ext:
                raise forms.ValidationError(
                    f"File type '{ext}' is not allowed. "
                    f"Allowed types: {', '.join(allowed_ext)}"
                )
            
            # Check file size (max 50MB)
            max_size = 50 * 1024 * 1024  # 50MB
            if file.size > max_size:
                raise forms.ValidationError(
                    f"File size ({file.size / 1024 / 1024:.2f}MB) exceeds "
                    f"maximum allowed size (50MB)"
                )
        
        return file

