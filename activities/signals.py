from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import Activity
from audit.models import AuditLog
import logging

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Activity)
def activity_pre_save(sender, instance, **kwargs):
    # Attach a snapshot of the existing record (if any) to instance
    if instance.pk:
        try:
            prev = Activity.objects.get(pk=instance.pk)
            instance._pre_save_snapshot = {
                'status_id': prev.status_id,
                'activity_id': prev.activity_id,
                'name': prev.name,
                'responsible_officer_id': prev.responsible_officer_id,
            }
        except Activity.DoesNotExist:
            instance._pre_save_snapshot = None
    else:
        instance._pre_save_snapshot = None


@receiver(post_save, sender=Activity)
def activity_post_save(sender, instance, created, **kwargs):
    if created:
        AuditLog.objects.create(
            user=None,
            activity_id=instance.pk,
            action='Activity created',
            object_repr=str(instance),
        )
    else:
        prev = getattr(instance, '_pre_save_snapshot', None)
        if prev:
            if prev.get('status_id') != instance.status_id:
                from masters.models import ActivityStatus
                try:
                    old_name = ActivityStatus.objects.get(pk=prev['status_id']).name
                except ActivityStatus.DoesNotExist:
                    old_name = str(prev['status_id'])
                new_name = instance.status.name if instance.status_id else 'Unset'
                AuditLog.objects.create(
                    user=None,
                    activity_id=instance.pk,
                    action='Status changed',
                    object_repr=str(instance),
                    change_description=f'Changed from "{old_name}" to "{new_name}"',
                )
            if prev.get('name') != instance.name:
                AuditLog.objects.create(
                    user=None,
                    activity_id=instance.pk,
                    action='Activity name changed',
                    object_repr=str(instance),
                    change_description=f'Changed from "{prev["name"]}" to "{instance.name}"',
                )


# ============================================================================
# NOTIFICATION SIGNALS
# ============================================================================

@receiver(post_save, sender=Activity)
def notify_on_activity_assignment(sender, instance, created, **kwargs):
    """
    Signal handler to send notification when responsible officer is assigned/changed
    """
    try:
        from services.notifications import send_assignment_notification
        
        prev_snapshot = getattr(instance, '_pre_save_snapshot', None)
        
        # Check if responsible officer was changed
        if not created and prev_snapshot:
            if prev_snapshot.get('responsible_officer_id') != instance.responsible_officer_id:
                if instance.responsible_officer:
                    send_assignment_notification(
                        activity=instance,
                        recipient_user=instance.responsible_officer,
                        assigned_by=None
                    )
    except Exception as e:
        logger.error(f"Error in notify_on_activity_assignment: {str(e)}")


@receiver(post_save, sender=Activity)
def notify_on_status_change(sender, instance, created, **kwargs):
    """
    Signal handler to send notification when activity status changes
    """
    try:
        from services.notifications import send_status_change_notification
        
        prev_snapshot = getattr(instance, '_pre_save_snapshot', None)
        
        if not created and prev_snapshot:
            if prev_snapshot.get('status_id') != instance.status_id:
                old_status_id = prev_snapshot.get('status_id')
                old_status_name = 'Previous'
                
                # Get old status name if possible
                if old_status_id:
                    try:
                        from masters.models import ActivityStatus
                        old_status_obj = ActivityStatus.objects.get(id=old_status_id)
                        old_status_name = old_status_obj.name
                    except:
                        pass
                
                new_status_name = instance.status.name if instance.status else 'Unset'
                
                send_status_change_notification(
                    activity=instance,
                    old_status=old_status_name,
                    new_status=new_status_name,
                    changed_by=None
                )
    except Exception as e:
        logger.error(f"Error in notify_on_status_change: {str(e)}")
