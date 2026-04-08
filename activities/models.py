from typing import Optional

from django.db import models
from django.conf import settings
from django.utils import timezone
from masters.models import (
    Funder,
    ActivityStatus,
    Currency,
    ProcurementType,
    ActivityCategory,
    ActivitySubCategory,
)
from accounts.models import Cluster
from django.db import transaction, IntegrityError
import calendar
from datetime import date

class Activity(models.Model):
    activity_id=models.CharField(max_length=15,unique=True)
    name=models.TextField()
    # Legacy category field kept for backward compatibility with older records.
    category=models.JSONField(default=list, blank=True, help_text="Legacy activity categories")
    categories = models.ManyToManyField(
        ActivityCategory,
        blank=True,
        related_name='activities',
    )
    sub_categories = models.ManyToManyField(
        ActivitySubCategory,
        blank=True,
        related_name='activities',
    )
    year=models.IntegerField()
    # Activities may be co-funded and implemented by multiple clusters
    funders = models.ManyToManyField(Funder, blank=True, related_name='activities')
    clusters = models.ManyToManyField(Cluster, blank=True, related_name='activities')
    status=models.ForeignKey(ActivityStatus,on_delete=models.PROTECT)
    planned_month=models.DateField()
    quarter=models.IntegerField(null=True,blank=True)
    fully_implemented_by=models.DateField(null=True,blank=True)
    actual_start_date=models.DateField(null=True,blank=True)
    actual_completion_date=models.DateField(null=True,blank=True)
    total_budget=models.DecimalField(max_digits=14,decimal_places=2)
    disbursed_amount=models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True)
    currency=models.ForeignKey(Currency, null=True, blank=True, on_delete=models.PROTECT)
    responsible_officer=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    retired=models.BooleanField(default=False, help_text="True if activity has been financially retired")
    deleted=models.BooleanField(default=False, help_text="Soft delete flag")
    technical_report_available=models.BooleanField(default=False)
    notes=models.TextField(blank=True)
    
    # ============================================================================
    # RECURRENCE FIELDS
    # ============================================================================
    is_recurring = models.BooleanField(default=False, help_text="Mark if this activity repeats on a schedule")
    RECURRENCE_PATTERN_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('bi_annual', 'Bi-Annual (every 6 months)'),
        ('annual', 'Annual'),
    ]
    recurrence_pattern = models.CharField(
        max_length=20,
        choices=RECURRENCE_PATTERN_CHOICES,
        default='monthly',
        null=True,
        blank=True,
        help_text="Pattern for recurring activities"
    )
    recurrence_interval = models.PositiveIntegerField(
        default=1,
        null=True,
        blank=True,
        help_text="Repeat every N periods (e.g., every 1 month, every 2 quarters)"
    )
    recurrence_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Stop generating instances after this date; leave blank for indefinite"
    )
    parent_activity = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_instances',
        help_text="If this is a recurring instance, references the template/parent activity"
    )
    generated_from_recurrence = models.BooleanField(
        default=False,
        help_text="True if this activity was auto-generated from a recurring template"
    )
    
    # ============================================================================
    # PROCUREMENT FIELDS
    # ============================================================================
    is_procurement = models.BooleanField(
        default=False,
        help_text="True if this entire activity is a procurement"
    )
    # Temporary field during migration - will be removed
    procurement_type_old = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Old procurement type field (temporary during migration)"
    )
    procurement_type = models.ForeignKey(
        ProcurementType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Type of procurement"
    )
    procurement_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amount of total budget allocated to procurement (leave blank if no procurement)"
    )
    procurement_breakdowns = models.JSONField(
        null=True,
        blank=True,
        help_text="Detailed breakdown of procurement items: [{type, amount, description}, ...]"
    )
    has_partial_procurement = models.BooleanField(
        default=False,
        help_text="Auto-set to True if procurement_amount is set and < total_budget"
    )
    is_construction = models.BooleanField(
        default=False,
        help_text="True if this activity is a construction activity",
    )

    in_procurement_plan = models.BooleanField(
        default=False,
        help_text="True if this activity is in the procurement plan",
    )
    
    class Meta:
        ordering = ['-year', 'activity_id']
        indexes = [
            models.Index(fields=['is_recurring']),
            models.Index(fields=['is_procurement']),
            models.Index(fields=['parent_activity']),
            models.Index(fields=['recurrence_end_date']),
            models.Index(fields=['year', 'planned_month']),
        ]

    def balance(self):
        from decimal import Decimal
        tb = self.total_budget or Decimal('0.00')
        da = self.disbursed_amount or Decimal('0.00')
        return tb - da

    def get_category_display_list(self):
        names = list(self.categories.values_list('name', flat=True))
        if names:
            return names
        if isinstance(self.category, list):
            return [str(value) for value in self.category]
        return []

    def get_sub_category_display_list(self):
        return list(self.sub_categories.values_list('name', flat=True))

    def clean(self):
        # Validate numeric fields
        from django.core.exceptions import ValidationError
        if self.total_budget is None:
            raise ValidationError({'total_budget': 'Total budget is required.'})
        if self.total_budget < 0:
            raise ValidationError({'total_budget': 'Total budget must be non-negative.'})
        if self.disbursed_amount is not None and self.disbursed_amount < 0:
            raise ValidationError({'disbursed_amount': 'Disbursed amount must be non-negative.'})
        if self.disbursed_amount and self.disbursed_amount > self.total_budget:
            raise ValidationError({'disbursed_amount': 'Disbursed cannot exceed total budget.'})
        
        # Validate procurement fields
        if self.procurement_amount is not None:
            if self.procurement_amount < 0:
                raise ValidationError({'procurement_amount': 'Procurement amount must be non-negative.'})
            if self.procurement_amount > self.total_budget:
                raise ValidationError({'procurement_amount': 'Procurement amount cannot exceed total budget.'})
        
        # Validate recurrence fields
        if self.is_recurring:
            if not self.recurrence_pattern:
                raise ValidationError({'recurrence_pattern': 'Recurrence pattern is required when recurring is enabled.'})
            if self.recurrence_interval is None or self.recurrence_interval < 1:
                raise ValidationError({'recurrence_interval': 'Recurrence interval must be at least 1.'})

        if self.category and not isinstance(self.category, list):
            raise ValidationError({'category': 'Legacy category data must be a list.'})
        
        # Cannot mark a generated instance as recurring
        if self.generated_from_recurrence and self.is_recurring:
            raise ValidationError({'is_recurring': 'Generated instances cannot be marked as recurring. Only parent activities can recur.'})


    def _compute_last_day_of_month(self, dt: date) -> date:
        # Return date representing the last day of dt's month
        last_day = calendar.monthrange(dt.year, dt.month)[1]
        return date(dt.year, dt.month, last_day)

    def _compute_quarter(self, dt: date) -> int:
        return ((dt.month - 1) // 3) + 1

    def _next_sequence_for_year(self, year: int) -> int:
        # Find highest numeric suffix for activities in the same year and return next
        qs = Activity.objects.filter(year=year).values_list('activity_id', flat=True)
        max_seq = 0
        for aid in qs:
            try:
                seq = int(aid.split('-')[-1])
                if seq > max_seq:
                    max_seq = seq
            except Exception:
                continue
        return max_seq + 1

    @staticmethod
    def _is_fully_implemented_status_name(name: Optional[str]) -> bool:
        if not name:
            return False
        return 'fully implemented' in name.strip().lower()

    def _apply_actual_completion_date_when_fully_implemented(self):
        """Set actual_completion_date when status becomes Fully Implemented (matches seed name)."""
        if not self.status_id:
            return
        try:
            status_name = self.status.name
        except Exception:
            return
        if not self._is_fully_implemented_status_name(status_name):
            return
        old_full = False
        if self.pk:
            prev = (
                Activity.objects.filter(pk=self.pk)
                .select_related('status')
                .first()
            )
            if prev and prev.status:
                old_full = self._is_fully_implemented_status_name(prev.status.name)
        if not old_full:
            self.actual_completion_date = timezone.localdate()

    def save(self, *args, **kwargs):
        # Ensure year is populated from planned_month
        if self.planned_month:
            self.year = self.planned_month.year

        # Ensure planned_month stored as last day of month
        if self.planned_month:
            self.planned_month = self._compute_last_day_of_month(self.planned_month)
            self.quarter = self._compute_quarter(self.planned_month)

        # Auto-generate activity_id if missing
        if not self.activity_id:
            if not self.year:
                self.year = date.today().year

        # Ensure currency default if not set
        if not self.currency:
            default_currency = Currency.objects.filter(is_default=True).first()
            if default_currency:
                self.currency = default_currency

        # Handle safe concurrent creation (retry on activity_id collision)
        if not self.activity_id and self._state.adding:
            last_error = None
            yy = str(self.year)[-2:]
            seq = self._next_sequence_for_year(self.year)
            for attempt in range(10):  # Increased retries
                try:
                    with transaction.atomic():
                        self.activity_id = f"Y{yy}-{seq:06d}"
                        self._apply_actual_completion_date_when_fully_implemented()
                        super().save(*args, **kwargs)
                    return
                except IntegrityError as e:
                    last_error = e
                    seq += 1  # Increment sequence on collision
                    continue
            # If still failing after retries, bubble up
            raise last_error
        
        # Auto-set has_partial_procurement flag based on procurement_amount or breakdowns
        from decimal import Decimal
        
        # Calculate total procurement amount from breakdowns if exists
        procurement_total = Decimal('0')
        if self.procurement_breakdowns and isinstance(self.procurement_breakdowns, list):
            for item in self.procurement_breakdowns:
                if isinstance(item, dict) and 'amount' in item:
                    try:
                        procurement_total += Decimal(str(item['amount']))
                    except (ValueError, TypeError):
                        pass
        elif self.procurement_amount is not None:
            # Fallback to legacy procurement_amount field
            procurement_total = self.procurement_amount
        
        # Set procurement_amount to the calculated total for reporting
        self.procurement_amount = procurement_total if procurement_total > Decimal('0') else None
        
        # Set flags based on total procurement amount
        if procurement_total > Decimal('0'):
            if procurement_total < self.total_budget:
                self.has_partial_procurement = True
                self.is_procurement = False  # Activity has procurement but not entirely
            elif procurement_total >= self.total_budget:
                self.is_procurement = True
                self.has_partial_procurement = False  # Entire activity is procurement
        else:
            self.has_partial_procurement = False
            self.is_procurement = False

        self._apply_actual_completion_date_when_fully_implemented()
        super().save(*args, **kwargs)

    def __str__(self): return self.activity_id


class ActivityAttachment(models.Model):
    """Model to store file attachments for activities with version control."""
    
    DOCUMENT_TYPE_CHOICES = [
        ('report', 'Technical Report'),
        ('proposal', 'Proposal Document'),
        ('invoice', 'Invoice'),
        ('receipt', 'Receipt'),
        ('other', 'Other Document'),
    ]
    
    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('docx', 'Word Document'),
        ('xlsx', 'Excel Spreadsheet'),
        ('other', 'Other'),
    ]
    
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='activity_attachments/%Y/%m/%d/')
    filename = models.CharField(max_length=255)
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES, default='report')
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    version = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='uploaded_attachments')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    file_size = models.BigIntegerField(help_text="File size in bytes")
    is_latest = models.BooleanField(default=True, help_text="Indicates if this is the latest version")
    is_deleted = models.BooleanField(default=False, help_text="Soft delete flag for version control")
    
    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['activity', 'is_latest']),
            models.Index(fields=['document_type', 'is_deleted']),
            models.Index(fields=['uploaded_at']),
        ]
    
    def save(self, *args, **kwargs):
        """Override save to determine file type and extract filename."""
        import os
        
        # Extract filename if not set
        if not self.filename and self.file:
            self.filename = self.file.name.split('/')[-1]
        
        # Determine file type from extension
        if self.file:
            ext = os.path.splitext(self.filename)[1].lower()
            if ext == '.pdf':
                self.file_type = 'pdf'
            elif ext in ['.docx', '.doc']:
                self.file_type = 'docx'
            elif ext in ['.xlsx', '.xls']:
                self.file_type = 'xlsx'
            else:
                self.file_type = 'other'
            
            # Get file size
            self.file_size = self.file.size
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.activity.activity_id} - {self.filename} (v{self.version})"
    
    @classmethod
    def get_versions(cls, activity, document_type=None):
        """Get all versions of documents for an activity."""
        query = cls.objects.filter(activity=activity, is_deleted=False)
        if document_type:
            query = query.filter(document_type=document_type)
        return query.order_by('document_type', '-version')
    
    @classmethod
    def upload_new_version(cls, activity, file, document_type, description='', uploaded_by=None):
        """Upload a new version of a document."""
        # Mark previous versions as not latest
        cls.objects.filter(
            activity=activity,
            document_type=document_type,
            is_deleted=False
        ).update(is_latest=False)
        
        # Get next version number
        last_version = cls.objects.filter(
            activity=activity,
            document_type=document_type
        ).aggregate(models.Max('version'))['version__max'] or 0
        
        # Create new attachment
        attachment = cls.objects.create(
            activity=activity,
            file=file,
            document_type=document_type,
            version=last_version + 1,
            description=description,
            uploaded_by=uploaded_by,
            is_latest=True
        )
        
        return attachment

# ============================================================================
# NOTIFICATION MODELS
# ============================================================================

class NotificationLog(models.Model):
    """Model to track email notifications sent to users."""
    
    NOTIFICATION_TYPE_CHOICES = [
        ('assignment', 'Activity Assignment'),
        ('status_change', 'Status Change'),
        ('due_date_alert', 'Due Date Alert'),
        ('update', 'Activity Update'),
        ('comment', 'New Comment'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('retrying', 'Retrying'),
    ]
    
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='notifications')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='received_notifications')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPE_CHOICES, default='update')
    subject = models.CharField(max_length=255)
    email_address = models.EmailField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    message = models.TextField()
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    is_read = models.BooleanField(default=False)
    
    # Audit
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_notifications')
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['activity', 'recipient']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['notification_type']),
        ]
    
    def __str__(self):
        return f"{self.notification_type} - {self.recipient.email if self.recipient else self.email_address}"
    
    def mark_as_sent(self):
        """Mark notification as sent"""
        from django.utils import timezone
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save()
    
    def mark_as_failed(self, error_msg=''):
        """Mark notification as failed"""
        self.status = 'failed'
        self.error_message = error_msg
        self.retry_count += 1
        self.save()


class NotificationPreference(models.Model):
    """Model to store user notification preferences."""
    
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_preference')
    
    # Notification types
    notify_on_assignment = models.BooleanField(default=True)
    notify_on_status_change = models.BooleanField(default=True)
    notify_on_due_date_alert = models.BooleanField(default=True)
    notify_on_activity_update = models.BooleanField(default=True)
    notify_on_comment = models.BooleanField(default=True)
    
    # Email frequency
    email_immediately = models.BooleanField(default=True)
    email_daily_digest = models.BooleanField(default=False)
    email_weekly_digest = models.BooleanField(default=False)
    
    # Timing
    quiet_hours_start = models.TimeField(null=True, blank=True, help_text="Don't send emails before this time")
    quiet_hours_end = models.TimeField(null=True, blank=True, help_text="Don't send emails after this time")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Notification preferences for {self.user.get_full_name()}"
    
    @classmethod
    def get_or_create_for_user(cls, user):
        """Get or create notification preference for user"""
        pref, created = cls.objects.get_or_create(user=user)
        return pref