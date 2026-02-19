"""Fleet Management Notification API.

Public functions for fleet-related notifications that enqueue work via Django tasks.
The actual email rendering/sending happens in `services.fleet_notification_core`.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _serialize_pk(value):
    """Return a task-safe identifier value for enqueue payloads."""
    if value is None:
        return None
    return str(value)


def send_transport_request_submitted_notification(transport_request) -> bool:
    """Send notification when a transport request is submitted for approval."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    request_id = _serialize_pk(getattr(transport_request, "pk", None))
    if not request_id:
        return False

    try:
        from services.fleet_notification_tasks import task_send_transport_request_submitted_notification
        task_send_transport_request_submitted_notification.enqueue(request_id)
        return True
    except Exception:
        logger.exception("Failed to enqueue transport request submitted notification; falling back to sync")
        from services.fleet_notification_core import send_transport_request_submitted_notification_sync
        return send_transport_request_submitted_notification_sync(transport_request)


def send_transport_request_approved_notification(transport_request, approved_by=None) -> bool:
    """Send notification when a transport request is approved."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    request_id = _serialize_pk(getattr(transport_request, "pk", None))
    if not request_id:
        return False

    approved_by_id = _serialize_pk(getattr(approved_by, "pk", None)) if approved_by else None

    try:
        from services.fleet_notification_tasks import task_send_transport_request_approved_notification
        task_send_transport_request_approved_notification.enqueue(request_id, approved_by_id)
        return True
    except Exception:
        logger.exception("Failed to enqueue transport request approved notification; falling back to sync")
        from services.fleet_notification_core import send_transport_request_approved_notification_sync
        return send_transport_request_approved_notification_sync(transport_request, approved_by=approved_by)


def send_transport_request_rejected_notification(transport_request, rejected_by=None, rejection_reason="") -> bool:
    """Send notification when a transport request is rejected."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    request_id = _serialize_pk(getattr(transport_request, "pk", None))
    if not request_id:
        return False

    rejected_by_id = _serialize_pk(getattr(rejected_by, "pk", None)) if rejected_by else None

    try:
        from services.fleet_notification_tasks import task_send_transport_request_rejected_notification
        task_send_transport_request_rejected_notification.enqueue(request_id, rejected_by_id, rejection_reason)
        return True
    except Exception:
        logger.exception("Failed to enqueue transport request rejected notification; falling back to sync")
        from services.fleet_notification_core import send_transport_request_rejected_notification_sync
        return send_transport_request_rejected_notification_sync(transport_request, rejected_by=rejected_by, rejection_reason=rejection_reason)


def send_trip_allocated_notification(trip_allocation, allocated_by=None) -> bool:
    """Send notification when a trip is allocated to a driver."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    allocation_id = _serialize_pk(getattr(trip_allocation, "pk", None))
    if not allocation_id:
        return False

    allocated_by_id = _serialize_pk(getattr(allocated_by, "pk", None)) if allocated_by else None

    try:
        from services.fleet_notification_tasks import task_send_trip_allocated_notification
        task_send_trip_allocated_notification.enqueue(allocation_id, allocated_by_id)
        return True
    except Exception:
        logger.exception("Failed to enqueue trip allocated notification; falling back to sync")
        from services.fleet_notification_core import send_trip_allocated_notification_sync
        return send_trip_allocated_notification_sync(trip_allocation, allocated_by=allocated_by)


def send_trip_confirmed_notification(trip_allocation, confirmed_by=None) -> bool:
    """Send notification when a driver confirms a trip allocation."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    allocation_id = _serialize_pk(getattr(trip_allocation, "pk", None))
    if not allocation_id:
        return False

    confirmed_by_id = _serialize_pk(getattr(confirmed_by, "pk", None)) if confirmed_by else None

    try:
        from services.fleet_notification_tasks import task_send_trip_confirmed_notification
        task_send_trip_confirmed_notification.enqueue(allocation_id, confirmed_by_id)
        return True
    except Exception:
        logger.exception("Failed to enqueue trip confirmed notification; falling back to sync")
        from services.fleet_notification_core import send_trip_confirmed_notification_sync
        return send_trip_confirmed_notification_sync(trip_allocation, confirmed_by=confirmed_by)


def send_trip_started_notification(trip_allocation, started_by=None) -> bool:
    """Send notification when a trip is started."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    allocation_id = _serialize_pk(getattr(trip_allocation, "pk", None))
    if not allocation_id:
        return False

    started_by_id = _serialize_pk(getattr(started_by, "pk", None)) if started_by else None

    try:
        from services.fleet_notification_tasks import task_send_trip_started_notification
        task_send_trip_started_notification.enqueue(allocation_id, started_by_id)
        return True
    except Exception:
        logger.exception("Failed to enqueue trip started notification; falling back to sync")
        from services.fleet_notification_core import send_trip_started_notification_sync
        return send_trip_started_notification_sync(trip_allocation, started_by=started_by)


def send_trip_completed_notification(trip_allocation, completed_by=None) -> bool:
    """Send notification when a trip is completed."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    allocation_id = _serialize_pk(getattr(trip_allocation, "pk", None))
    if not allocation_id:
        return False

    completed_by_id = _serialize_pk(getattr(completed_by, "pk", None)) if completed_by else None

    try:
        from services.fleet_notification_tasks import task_send_trip_completed_notification
        task_send_trip_completed_notification.enqueue(allocation_id, completed_by_id)
        return True
    except Exception:
        logger.exception("Failed to enqueue trip completed notification; falling back to sync")
        from services.fleet_notification_core import send_trip_completed_notification_sync
        return send_trip_completed_notification_sync(trip_allocation, completed_by=completed_by)


def send_trip_cancelled_notification(trip_allocation, cancelled_by=None, cancellation_reason="") -> bool:
    """Send notification when a trip is cancelled."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    allocation_id = _serialize_pk(getattr(trip_allocation, "pk", None))
    if not allocation_id:
        return False

    cancelled_by_id = _serialize_pk(getattr(cancelled_by, "pk", None)) if cancelled_by else None

    try:
        from services.fleet_notification_tasks import task_send_trip_cancelled_notification
        task_send_trip_cancelled_notification.enqueue(allocation_id, cancelled_by_id, cancellation_reason)
        return True
    except Exception:
        logger.exception("Failed to enqueue trip cancelled notification; falling back to sync")
        from services.fleet_notification_core import send_trip_cancelled_notification_sync
        return send_trip_cancelled_notification_sync(trip_allocation, cancelled_by=cancelled_by, cancellation_reason=cancellation_reason)