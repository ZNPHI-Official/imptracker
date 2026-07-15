"""
Removes all synthetic seed data created by the seed_data command.

Run with: python manage.py flush_seed
Skip the confirmation prompt: python manage.py flush_seed --no-input

What is deleted:
  - All TripAssignment, FuelRecord, MaintenanceRecord records
  - All TransportRequest records
  - All Vehicle and Driver records
  - User accounts whose username starts with 'seed_'

What is NOT deleted:
  - Provinces, districts, departments (reference fixture data)
  - Real user accounts (those without the 'seed_' prefix)
  - Auth groups
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from bookings.models import TransportRequest, TripAssignment
from fleet.models import Driver, FuelRecord, MaintenanceRecord, Vehicle

User = get_user_model()

SEED_PREFIX = 'seed_'


class Command(BaseCommand):
    help = 'Remove all synthetic seed data (vehicles, drivers, requests, assignments, fuel/maintenance records, seed user accounts).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Skip the confirmation prompt.',
        )

    def handle(self, *args, **options):
        if not options['no_input']:
            self.stdout.write(self.style.WARNING(
                'This will permanently delete:\n'
                '  • All vehicles, drivers, trip assignments\n'
                '  • All transport requests, fuel records, maintenance records\n'
                '  • All user accounts with usernames starting with "seed_"\n'
                '\nProvinces, districts, departments, and real user accounts are kept.'
            ))
            confirm = input('\nType "yes" to continue, or anything else to cancel: ')
            if confirm.strip().lower() != 'yes':
                self.stdout.write('Aborted.')
                return

        # Delete in FK-dependency order to avoid constraint violations.
        ta = TripAssignment.objects.all().delete()[0]
        fu = FuelRecord.objects.all().delete()[0]
        mr = MaintenanceRecord.objects.all().delete()[0]
        tr = TransportRequest.objects.all().delete()[0]
        v  = Vehicle.objects.all().delete()[0]
        d  = Driver.objects.all().delete()[0]
        u  = User.objects.filter(username__startswith=SEED_PREFIX).delete()[0]

        self.stdout.write(self.style.SUCCESS(
            f'Flushed: {v} vehicles, {d} drivers, '
            f'{tr} requests, {ta} assignments, '
            f'{fu} fuel records, {mr} maintenance records, '
            f'{u} seed user accounts.'
        ))
