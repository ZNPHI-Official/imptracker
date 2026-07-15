import datetime

from django.core.management.base import BaseCommand

from bookings.models import TransportRequest
from bookings.services import sync_fleet_statuses


class Command(BaseCommand):
    help = (
        'Transition approved requests to In Progress when their trip has started, '
        'and in-progress requests to Completed when their trip has ended, then '
        'reconcile vehicle/driver status with the resulting active trips. '
        'Intended to be called daily via cron (see CRONJOBS in settings).'
    )

    def handle(self, *args, **options):
        today = datetime.date.today()

        # Approved → In Progress: trip start date has been reached.
        started = TransportRequest.objects.filter(
            status='Approved',
            period_from__lte=today,
        ).update(status='In Progress')

        # In Progress → Completed: trip end date has passed.
        completed = TransportRequest.objects.filter(
            status='In Progress',
            period_to__lt=today,
        ).update(status='Completed')

        # Mark vehicles/drivers on now-active trips as On Trip / On Assignment, and
        # release those whose trips just ended. Full reconcile keeps this correct
        # regardless of how the request statuses were reached (cron or seed).
        sync_fleet_statuses()

        self.stdout.write(
            self.style.SUCCESS(
                f'run_transitions: {started} -> In Progress, {completed} -> Completed'
            )
        )
