from django.apps import apps
from django.tasks import task

from services.fleet_notification_core import (
    send_transport_request_submitted_notification_sync,
    send_transport_request_approved_notification_sync,
    send_transport_request_rejected_notification_sync,
    send_trip_allocated_notification_sync,
    send_trip_confirmed_notification_sync,
    send_trip_started_notification_sync,
    send_trip_completed_notification_sync,
    send_trip_cancelled_notification_sync,
)


@task
def task_send_transport_request_submitted_notification(transport_request_id: int) -> bool:
    TransportRequest = apps.get_model("fleet", "TransportRequest")
    transport_request = TransportRequest.objects.get(pk=transport_request_id)
    return send_transport_request_submitted_notification_sync(transport_request)


@task
def task_send_transport_request_approved_notification(transport_request_id: int, approved_by_id: int | None = None) -> bool:
    TransportRequest = apps.get_model("fleet", "TransportRequest")
    User = apps.get_model("accounts", "User")
    transport_request = TransportRequest.objects.get(pk=transport_request_id)
    approved_by = User.objects.get(pk=approved_by_id) if approved_by_id else None
    return send_transport_request_approved_notification_sync(transport_request, approved_by=approved_by)


@task
def task_send_transport_request_rejected_notification(transport_request_id: int, rejected_by_id: int | None = None, rejection_reason: str = "") -> bool:
    TransportRequest = apps.get_model("fleet", "TransportRequest")
    User = apps.get_model("accounts", "User")
    transport_request = TransportRequest.objects.get(pk=transport_request_id)
    rejected_by = User.objects.get(pk=rejected_by_id) if rejected_by_id else None
    return send_transport_request_rejected_notification_sync(transport_request, rejected_by=rejected_by, rejection_reason=rejection_reason)


@task
def task_send_trip_allocated_notification(trip_allocation_id: int, allocated_by_id: int | None = None) -> bool:
    TripAllocation = apps.get_model("fleet", "TripAllocation")
    User = apps.get_model("accounts", "User")
    trip_allocation = TripAllocation.objects.get(pk=trip_allocation_id)
    allocated_by = User.objects.get(pk=allocated_by_id) if allocated_by_id else None
    return send_trip_allocated_notification_sync(trip_allocation, allocated_by=allocated_by)


@task
def task_send_trip_confirmed_notification(trip_allocation_id: int, confirmed_by_id: int | None = None) -> bool:
    TripAllocation = apps.get_model("fleet", "TripAllocation")
    User = apps.get_model("accounts", "User")
    trip_allocation = TripAllocation.objects.get(pk=trip_allocation_id)
    confirmed_by = User.objects.get(pk=confirmed_by_id) if confirmed_by_id else None
    return send_trip_confirmed_notification_sync(trip_allocation, confirmed_by=confirmed_by)


@task
def task_send_trip_started_notification(trip_allocation_id: int, started_by_id: int | None = None) -> bool:
    TripAllocation = apps.get_model("fleet", "TripAllocation")
    User = apps.get_model("accounts", "User")
    trip_allocation = TripAllocation.objects.get(pk=trip_allocation_id)
    started_by = User.objects.get(pk=started_by_id) if started_by_id else None
    return send_trip_started_notification_sync(trip_allocation, started_by=started_by)


@task
def task_send_trip_completed_notification(trip_allocation_id: int, completed_by_id: int | None = None) -> bool:
    TripAllocation = apps.get_model("fleet", "TripAllocation")
    User = apps.get_model("accounts", "User")
    trip_allocation = TripAllocation.objects.get(pk=trip_allocation_id)
    completed_by = User.objects.get(pk=completed_by_id) if completed_by_id else None
    return send_trip_completed_notification_sync(trip_allocation, completed_by=completed_by)


@task
def task_send_trip_cancelled_notification(trip_allocation_id: int, cancelled_by_id: int | None = None, cancellation_reason: str = "") -> bool:
    TripAllocation = apps.get_model("fleet", "TripAllocation")
    User = apps.get_model("accounts", "User")
    trip_allocation = TripAllocation.objects.get(pk=trip_allocation_id)
    cancelled_by = User.objects.get(pk=cancelled_by_id) if cancelled_by_id else None
    return send_trip_cancelled_notification_sync(trip_allocation, cancelled_by=cancelled_by, cancellation_reason=cancellation_reason)