from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from .models import Activity, ActivityAttachment, NotificationLog, NotificationPreference


@admin.register(Activity)
class ActivityAdmin(ImportExportModelAdmin):
    def cluster_display(self, obj):
        return ', '.join([c.short_name for c in obj.clusters.all()]) if obj.clusters.exists() else ''
    cluster_display.short_description = 'Cluster'

    list_display = ('activity_id', 'name', 'year', 'cluster_display', 'status', 'total_budget', 'disbursed_amount', 'currency', 'retired', 'deleted')
    list_filter = ('year', 'clusters', 'status', 'retired', 'deleted')
    search_fields = ('activity_id', 'name')


@admin.register(ActivityAttachment)
class ActivityAttachmentAdmin(admin.ModelAdmin):
    def uploaded_by_display(self, obj):
        return obj.uploaded_by.get_full_name() if obj.uploaded_by else 'System'
    uploaded_by_display.short_description = 'Uploaded By'
    
    list_display = ('filename', 'activity', 'document_type', 'version', 'uploaded_by_display', 'uploaded_at', 'is_latest', 'is_deleted')
    list_filter = ('document_type', 'file_type', 'is_latest', 'is_deleted', 'uploaded_at')
    search_fields = ('filename', 'activity__name', 'activity__activity_id', 'description')
    readonly_fields = ('file_type', 'file_size', 'uploaded_at', 'updated_at')
    
    fieldsets = (
        ('Document Information', {
            'fields': ('activity', 'filename', 'document_type', 'description')
        }),
        ('File Details', {
            'fields': ('file', 'file_type', 'file_size')
        }),
        ('Version Control', {
            'fields': ('version', 'is_latest')
        }),
        ('Status', {
            'fields': ('is_deleted',)
        }),
        ('Audit Information', {
            'fields': ('uploaded_by', 'uploaded_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ['activity', 'filename', 'document_type', 'file', 'version', 'uploaded_by', 'uploaded_at']
        return self.readonly_fields


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    def sender_display(self, obj):
        return obj.sender.get_full_name() if obj.sender else 'System'
    sender_display.short_description = 'Sent By'
    
    def recipient_display(self, obj):
        return obj.recipient.get_full_name() if obj.recipient else obj.email_address
    recipient_display.short_description = 'Recipient'
    
    list_display = ('subject', 'activity', 'notification_type', 'recipient_display', 'status', 'created_at', 'sent_at')
    list_filter = ('notification_type', 'status', 'created_at')
    search_fields = ('subject', 'email_address', 'activity__name', 'activity__activity_id')
    readonly_fields = ('created_at', 'sent_at', 'activity', 'recipient', 'email_address', 'message')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Notification Details', {
            'fields': ('activity', 'notification_type', 'subject')
        }),
        ('Recipient Information', {
            'fields': ('recipient', 'email_address')
        }),
        ('Status', {
            'fields': ('status', 'error_message', 'retry_count')
        }),
        ('Message', {
            'fields': ('message',)
        }),
        ('Timestamp', {
            'fields': ('created_at', 'sent_at'),
            'classes': ('collapse',)
        })
    )
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    def user_display(self, obj):
        return obj.user.get_full_name() or obj.user.username
    user_display.short_description = 'User'
    
    list_display = (
        'user_display',
        'notify_on_assignment',
        'notify_on_status_change',
        'notify_on_due_date_alert',
        'email_immediately'
    )
    list_filter = (
        'notify_on_assignment',
        'notify_on_status_change',
        'notify_on_due_date_alert',
        'email_immediately'
    )
    search_fields = ('user__first_name', 'user__last_name', 'user__username', 'user__email')
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Notification Types', {
            'fields': (
                'notify_on_assignment',
                'notify_on_status_change',
                'notify_on_due_date_alert',
                'notify_on_activity_update',
                'notify_on_comment'
            )
        }),
        ('Email Frequency', {
            'fields': (
                'email_immediately',
                'email_daily_digest',
                'email_weekly_digest'
            )
        }),
        ('Quiet Hours', {
            'fields': ('quiet_hours_start', 'quiet_hours_end'),
            'classes': ('collapse',),
            'description': 'Do not send emails outside these hours'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ('created_at', 'updated_at')
