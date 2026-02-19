"""
Management command to populate sample fleet data for testing.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from accounts.models import User
from fleet.models import Vehicle, Driver, VehicleStatus, DriverStatus


class Command(BaseCommand):
    help = 'Populate sample fleet data for testing'

    def handle(self, *args, **options):
        self.stdout.write('Creating sample fleet data...')

        # Create sample vehicles
        vehicles_data = [
            {
                'registration_number': 'ABC-001',
                'make': 'Toyota',
                'model': 'Corolla',
                'vehicle_type': 'sedan',
                'fuel_type': 'petrol',
                'assigned_location': 'Main Office',
            },
            {
                'registration_number': 'ABC-002',
                'make': 'Honda',
                'model': 'Civic',
                'vehicle_type': 'sedan',
                'fuel_type': 'petrol',
                'assigned_location': 'Main Office',
            },
            {
                'registration_number': 'XYZ-001',
                'make': 'Toyota',
                'model': 'Hiace',
                'vehicle_type': 'van',
                'fuel_type': 'diesel',
                'assigned_location': 'Branch Office',
            },
            {
                'registration_number': 'XYZ-002',
                'make': 'Nissan',
                'model': 'Urvan',
                'vehicle_type': 'van',
                'fuel_type': 'diesel',
                'assigned_location': 'Branch Office',
            },
            {
                'registration_number': 'TRK-001',
                'make': 'Isuzu',
                'model': 'NQR',
                'vehicle_type': 'truck',
                'fuel_type': 'diesel',
                'assigned_location': 'Warehouse',
            },
        ]

        for vehicle_data in vehicles_data:
            vehicle, created = Vehicle.objects.get_or_create(
                registration_number=vehicle_data['registration_number'],
                defaults=vehicle_data
            )
            if created:
                self.stdout.write(f'Created vehicle: {vehicle}')

        # Create sample drivers
        try:
            # Get some existing users to make drivers
            users = User.objects.filter(is_active=True)[:3]
            if not users:
                self.stdout.write(self.style.WARNING('No users found to create drivers'))
                return

            for i, user in enumerate(users):
                driver, created = Driver.objects.get_or_create(
                    user=user,
                    defaults={
                        'license_number': f'DRV-{user.id:03d}',
                        'phone_number': f'+123456789{i}',
                        'license_expiry_date': timezone.now().date() + timedelta(days=365),
                        'assigned_location': 'Main Office' if i % 2 == 0 else 'Branch Office',
                    }
                )
                if created:
                    self.stdout.write(f'Created driver: {driver}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating drivers: {e}'))

        self.stdout.write(self.style.SUCCESS('Sample fleet data created successfully'))