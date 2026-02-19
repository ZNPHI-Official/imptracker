"""Core synchronous fleet notification email sending.

This module contains the actual email rendering/sending and NotificationLog writes for fleet notifications.
It is called from background tasks in `services.fleet_notification_tasks`.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from activities.models import NotificationLog, NotificationPreference
from fleet.models import TransportRequest, TripAllocation

logger = logging.getLogger(__name__)


def absolute_url(path: str) -> str:
    """Generate absolute URL for the given path."""
    base = (getattr(settings, "SITE_URL", "") or "").strip()
    if not base:
        return ""
    base = base.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def display_name(user) -> str:
    """Get display name for a user."""
    if not user:
        return "System"
    full = (user.get_full_name() or "").strip()
    return full or getattr(user, "username", "System")


def get_transport_officers():
    """Get all users with transport officer role."""
    from accounts.models import User
    from fleet.models import FleetUserRole

    return User.objects.filter(
        groups__name=FleetUserRole.TRANSPORT_OFFICER
    ).distinct()


def send_transport_request_submitted_notification_sync(transport_request) -> bool:
    """Send notification when a transport request is submitted for approval."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    if not isinstance(transport_request, TransportRequest):
        return False

    # Get transport officers to notify
    transport_officers = get_transport_officers()
    if not transport_officers.exists():
        logger.warning("No transport officers found to notify about transport request submission")
        return False

    subject = f"Transport Request Submitted: {transport_request.request_id}"

    success_count = 0
    for officer in transport_officers:
        if not officer.email:
            continue

        try:
            # Create notification preference if it doesn't exist
            NotificationPreference.get_or_create_for_user(officer)

            context = {
                'transport_request': transport_request,
                'recipient': officer,
                'site_url': absolute_url(''),
                'request_url': absolute_url(f'/fleet/requests/{transport_request.pk}/'),
                'approve_url': absolute_url(f'/fleet/requests/{transport_request.pk}/approve/'),
            }

            html_message = render_to_string('fleet/emails/request_submitted.html', context)
            plain_message = strip_tags(html_message)

            # Send email
            email_sent = send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[officer.email],
                html_message=html_message,
                fail_silently=False,
            )

            # Log notification
            notification = NotificationLog.objects.create(
                transport_request=transport_request,
                recipient=officer,
                notification_type='transport_request_submitted',
                subject=subject,
                email_address=officer.email,
                message=plain_message,
                status='sent' if email_sent else 'failed',
                created_by=transport_request.requested_by,
            )

            if email_sent:
                notification.mark_as_sent()
                success_count += 1
            else:
                notification.mark_as_failed("Email sending failed")

        except Exception as e:
            logger.exception(f"Failed to send transport request submitted notification to {officer.email}")
            # Log failed notification
            NotificationLog.objects.create(
                transport_request=transport_request,
                recipient=officer,
                notification_type='transport_request_submitted',
                subject=subject,
                email_address=officer.email,
                message=f"Transport request {transport_request.request_id} submitted for approval",
                status='failed',
                error_message=str(e),
                created_by=transport_request.requested_by,
            )

    return success_count > 0


def send_transport_request_approved_notification_sync(transport_request, approved_by=None) -> bool:
    """Send notification when a transport request is approved."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    if not isinstance(transport_request, TransportRequest):
        return False

    # Notify the requestor
    recipient = transport_request.requested_by
    if not recipient or not recipient.email:
        return False

    try:
        # Create notification preference if it doesn't exist
        NotificationPreference.get_or_create_for_user(recipient)

        subject = f"Transport Request Approved: {transport_request.request_id}"

        context = {
            'transport_request': transport_request,
            'recipient': recipient,
            'approved_by': approved_by,
            'site_url': absolute_url(''),
            'request_url': absolute_url(f'/fleet/requests/{transport_request.pk}/'),
        }

        html_message = render_to_string('fleet/emails/request_approved.html', context)
        plain_message = strip_tags(html_message)

        # Send email
        email_sent = send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient.email],
            html_message=html_message,
            fail_silently=False,
        )

        # Log notification
        notification = NotificationLog.objects.create(
            transport_request=transport_request,
            recipient=recipient,
            notification_type='transport_request_approved',
            subject=subject,
            email_address=recipient.email,
            message=plain_message,
            status='sent' if email_sent else 'failed',
            created_by=approved_by,
        )

        if email_sent:
            notification.mark_as_sent()
            return True
        else:
            notification.mark_as_failed("Email sending failed")
            return False

    except Exception as e:
        logger.exception(f"Failed to send transport request approved notification to {recipient.email}")
        # Log failed notification
        NotificationLog.objects.create(
            transport_request=transport_request,
            recipient=recipient,
            notification_type='transport_request_approved',
            subject=f"Transport Request Approved: {transport_request.request_id}",
            email_address=recipient.email,
            message=f"Your transport request {transport_request.request_id} has been approved",
            status='failed',
            error_message=str(e),
            created_by=approved_by,
        )
        return False


def send_transport_request_rejected_notification_sync(transport_request, rejected_by=None, rejection_reason="") -> bool:
    """Send notification when a transport request is rejected."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    if not isinstance(transport_request, TransportRequest):
        return False

    # Notify the requestor
    recipient = transport_request.requested_by
    if not recipient or not recipient.email:
        return False

    try:
        # Create notification preference if it doesn't exist
        NotificationPreference.get_or_create_for_user(recipient)

        subject = f"Transport Request Rejected: {transport_request.request_id}"

        context = {
            'transport_request': transport_request,
            'recipient': recipient,
            'rejected_by': rejected_by,
            'rejection_reason': rejection_reason,
            'site_url': absolute_url(''),
            'request_url': absolute_url(f'/fleet/requests/{transport_request.pk}/'),
        }

        html_message = render_to_string('fleet/emails/request_rejected.html', context)
        plain_message = strip_tags(html_message)

        # Send email
        email_sent = send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient.email],
            html_message=html_message,
            fail_silently=False,
        )

        # Log notification
        notification = NotificationLog.objects.create(
            transport_request=transport_request,
            recipient=recipient,
            notification_type='transport_request_rejected',
            subject=subject,
            email_address=recipient.email,
            message=plain_message,
            status='sent' if email_sent else 'failed',
            created_by=rejected_by,
        )

        if email_sent:
            notification.mark_as_sent()
            return True
        else:
            notification.mark_as_failed("Email sending failed")
            return False

    except Exception as e:
        logger.exception(f"Failed to send transport request rejected notification to {recipient.email}")
        # Log failed notification
        NotificationLog.objects.create(
            transport_request=transport_request,
            recipient=recipient,
            notification_type='transport_request_rejected',
            subject=f"Transport Request Rejected: {transport_request.request_id}",
            email_address=recipient.email,
            message=f"Your transport request {transport_request.request_id} has been rejected",
            status='failed',
            error_message=str(e),
            created_by=rejected_by,
        )
        return False


def send_trip_allocated_notification_sync(trip_allocation, allocated_by=None) -> bool:
    """Send notification when a trip is allocated to a driver."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    if not isinstance(trip_allocation, TripAllocation):
        return False

    # Notify the driver
    driver = trip_allocation.driver
    if not driver or not driver.user or not driver.user.email:
        return False

    recipient = driver.user

    try:
        # Create notification preference if it doesn't exist
        NotificationPreference.get_or_create_for_user(recipient)

        subject = f"Trip Allocated: {trip_allocation.transport_request.request_id}"

        context = {
            'trip_allocation': trip_allocation,
            'transport_request': trip_allocation.transport_request,
            'recipient': recipient,
            'allocated_by': allocated_by,
            'site_url': absolute_url(''),
            'allocation_url': absolute_url(f'/fleet/allocations/{trip_allocation.pk}/confirm/'),
        }

        html_message = render_to_string('fleet/emails/trip_allocated.html', context)
        plain_message = strip_tags(html_message)

        # Send email
        email_sent = send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient.email],
            html_message=html_message,
            fail_silently=False,
        )

        # Log notification
        notification = NotificationLog.objects.create(
            trip_allocation=trip_allocation,
            transport_request=trip_allocation.transport_request,
            recipient=recipient,
            notification_type='trip_allocated',
            subject=subject,
            email_address=recipient.email,
            message=plain_message,
            status='sent' if email_sent else 'failed',
            created_by=allocated_by,
        )

        if email_sent:
            notification.mark_as_sent()
            return True
        else:
            notification.mark_as_failed("Email sending failed")
            return False

    except Exception as e:
        logger.exception(f"Failed to send trip allocated notification to {recipient.email}")
        # Log failed notification
        NotificationLog.objects.create(
            trip_allocation=trip_allocation,
            transport_request=trip_allocation.transport_request,
            recipient=recipient,
            notification_type='trip_allocated',
            subject=f"Trip Allocated: {trip_allocation.transport_request.request_id}",
            email_address=recipient.email,
            message=f"You have been allocated a trip for transport request {trip_allocation.transport_request.request_id}",
            status='failed',
            error_message=str(e),
            created_by=allocated_by,
        )
        return False


def send_trip_confirmed_notification_sync(trip_allocation, confirmed_by=None) -> bool:
    """Send notification when a driver confirms a trip allocation."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    if not isinstance(trip_allocation, TripAllocation):
        return False

    # Notify transport officers
    transport_officers = get_transport_officers()
    if not transport_officers.exists():
        logger.warning("No transport officers found to notify about trip confirmation")
        return False

    subject = f"Trip Confirmed: {trip_allocation.transport_request.request_id}"

    success_count = 0
    for officer in transport_officers:
        if not officer.email:
            continue

        try:
            # Create notification preference if it doesn't exist
            NotificationPreference.get_or_create_for_user(officer)

            context = {
                'trip_allocation': trip_allocation,
                'transport_request': trip_allocation.transport_request,
                'recipient': officer,
                'confirmed_by': confirmed_by,
                'site_url': absolute_url(''),
                'request_url': absolute_url(f'/fleet/requests/{trip_allocation.transport_request.pk}/'),
            }

            html_message = render_to_string('fleet/emails/trip_confirmed.html', context)
            plain_message = strip_tags(html_message)

            # Send email
            email_sent = send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[officer.email],
                html_message=html_message,
                fail_silently=False,
            )

            # Log notification
            notification = NotificationLog.objects.create(
                trip_allocation=trip_allocation,
                transport_request=trip_allocation.transport_request,
                recipient=officer,
                notification_type='trip_confirmed',
                subject=subject,
                email_address=officer.email,
                message=plain_message,
                status='sent' if email_sent else 'failed',
                created_by=confirmed_by,
            )

            if email_sent:
                notification.mark_as_sent()
                success_count += 1
            else:
                notification.mark_as_failed("Email sending failed")

        except Exception as e:
            logger.exception(f"Failed to send trip confirmed notification to {officer.email}")
            # Log failed notification
            NotificationLog.objects.create(
                trip_allocation=trip_allocation,
                transport_request=trip_allocation.transport_request,
                recipient=officer,
                notification_type='trip_confirmed',
                subject=subject,
                email_address=officer.email,
                message=f"Trip confirmed for transport request {trip_allocation.transport_request.request_id}",
                status='failed',
                error_message=str(e),
                created_by=confirmed_by,
            )

    return success_count > 0


def send_trip_started_notification_sync(trip_allocation, started_by=None) -> bool:
    """Send notification when a trip is started."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    if not isinstance(trip_allocation, TripAllocation):
        return False

    # Notify transport officers
    transport_officers = get_transport_officers()
    if not transport_officers.exists():
        logger.warning("No transport officers found to notify about trip start")
        return False

    subject = f"Trip Started: {trip_allocation.transport_request.request_id}"

    success_count = 0
    for officer in transport_officers:
        if not officer.email:
            continue

        try:
            # Create notification preference if it doesn't exist
            NotificationPreference.get_or_create_for_user(officer)

            context = {
                'trip_allocation': trip_allocation,
                'transport_request': trip_allocation.transport_request,
                'recipient': officer,
                'started_by': started_by,
                'site_url': absolute_url(''),
                'request_url': absolute_url(f'/fleet/requests/{trip_allocation.transport_request.pk}/'),
            }

            html_message = render_to_string('fleet/emails/trip_started.html', context)
            plain_message = strip_tags(html_message)

            # Send email
            email_sent = send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[officer.email],
                html_message=html_message,
                fail_silently=False,
            )

            # Log notification
            notification = NotificationLog.objects.create(
                trip_allocation=trip_allocation,
                transport_request=trip_allocation.transport_request,
                recipient=officer,
                notification_type='trip_started',
                subject=subject,
                email_address=officer.email,
                message=plain_message,
                status='sent' if email_sent else 'failed',
                created_by=started_by,
            )

            if email_sent:
                notification.mark_as_sent()
                success_count += 1
            else:
                notification.mark_as_failed("Email sending failed")

        except Exception as e:
            logger.exception(f"Failed to send trip started notification to {officer.email}")
            # Log failed notification
            NotificationLog.objects.create(
                trip_allocation=trip_allocation,
                transport_request=trip_allocation.transport_request,
                recipient=officer,
                notification_type='trip_started',
                subject=subject,
                email_address=officer.email,
                message=f"Trip started for transport request {trip_allocation.transport_request.request_id}",
                status='failed',
                error_message=str(e),
                created_by=started_by,
            )

    return success_count > 0


def send_trip_completed_notification_sync(trip_allocation, completed_by=None) -> bool:
    """Send notification when a trip is completed."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    if not isinstance(trip_allocation, TripAllocation):
        return False

    # Notify transport officers
    transport_officers = get_transport_officers()
    if not transport_officers.exists():
        logger.warning("No transport officers found to notify about trip completion")
        return False

    subject = f"Trip Completed: {trip_allocation.transport_request.request_id}"

    success_count = 0
    for officer in transport_officers:
        if not officer.email:
            continue

        try:
            # Create notification preference if it doesn't exist
            NotificationPreference.get_or_create_for_user(officer)

            context = {
                'trip_allocation': trip_allocation,
                'transport_request': trip_allocation.transport_request,
                'recipient': officer,
                'completed_by': completed_by,
                'site_url': absolute_url(''),
                'request_url': absolute_url(f'/fleet/requests/{trip_allocation.transport_request.pk}/'),
            }

            html_message = render_to_string('fleet/emails/trip_completed.html', context)
            plain_message = strip_tags(html_message)

            # Send email
            email_sent = send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[officer.email],
                html_message=html_message,
                fail_silently=False,
            )

            # Log notification
            notification = NotificationLog.objects.create(
                trip_allocation=trip_allocation,
                transport_request=trip_allocation.transport_request,
                recipient=officer,
                notification_type='trip_completed',
                subject=subject,
                email_address=officer.email,
                message=plain_message,
                status='sent' if email_sent else 'failed',
                created_by=completed_by,
            )

            if email_sent:
                notification.mark_as_sent()
                success_count += 1
            else:
                notification.mark_as_failed("Email sending failed")

        except Exception as e:
            logger.exception(f"Failed to send trip completed notification to {officer.email}")
            # Log failed notification
            NotificationLog.objects.create(
                trip_allocation=trip_allocation,
                transport_request=trip_allocation.transport_request,
                recipient=officer,
                notification_type='trip_completed',
                subject=subject,
                email_address=officer.email,
                message=f"Trip completed for transport request {trip_allocation.transport_request.request_id}",
                status='failed',
                error_message=str(e),
                created_by=completed_by,
            )

    return success_count > 0


def send_trip_cancelled_notification_sync(trip_allocation, cancelled_by=None, cancellation_reason="") -> bool:
    """Send notification when a trip is cancelled."""
    if not settings.NOTIFICATIONS_ENABLED:
        return False

    if not isinstance(trip_allocation, TripAllocation):
        return False

    # Notify both the driver and transport officers
    recipients = []

    # Add driver if they exist
    if trip_allocation.driver and trip_allocation.driver.user:
        recipients.append(trip_allocation.driver.user)

    # Add transport officers
    transport_officers = get_transport_officers()
    recipients.extend(transport_officers)

    if not recipients:
        logger.warning("No recipients found to notify about trip cancellation")
        return False

    subject = f"Trip Cancelled: {trip_allocation.transport_request.request_id}"

    success_count = 0
    for recipient in recipients:
        if not recipient.email:
            continue

        try:
            # Create notification preference if it doesn't exist
            NotificationPreference.get_or_create_for_user(recipient)

            context = {
                'trip_allocation': trip_allocation,
                'transport_request': trip_allocation.transport_request,
                'recipient': recipient,
                'cancelled_by': cancelled_by,
                'cancellation_reason': cancellation_reason,
                'site_url': absolute_url(''),
                'request_url': absolute_url(f'/fleet/requests/{trip_allocation.transport_request.pk}/'),
            }

            html_message = render_to_string('fleet/emails/trip_cancelled.html', context)
            plain_message = strip_tags(html_message)

            # Send email
            email_sent = send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                html_message=html_message,
                fail_silently=False,
            )

            # Log notification
            notification = NotificationLog.objects.create(
                trip_allocation=trip_allocation,
                transport_request=trip_allocation.transport_request,
                recipient=recipient,
                notification_type='trip_cancelled',
                subject=subject,
                email_address=recipient.email,
                message=plain_message,
                status='sent' if email_sent else 'failed',
                created_by=cancelled_by,
            )

            if email_sent:
                notification.mark_as_sent()
                success_count += 1
            else:
                notification.mark_as_failed("Email sending failed")

        except Exception as e:
            logger.exception(f"Failed to send trip cancelled notification to {recipient.email}")
            # Log failed notification
            NotificationLog.objects.create(
                trip_allocation=trip_allocation,
                transport_request=trip_allocation.transport_request,
                recipient=recipient,
                notification_type='trip_cancelled',
                subject=subject,
                email_address=recipient.email,
                message=f"Trip cancelled for transport request {trip_allocation.transport_request.request_id}",
                status='failed',
                error_message=str(e),
                created_by=cancelled_by,
            )

    return success_count > 0