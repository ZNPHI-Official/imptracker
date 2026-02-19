"""
Fleet trip execution tests - Phase 6.
"""

from datetime import timedelta

from django.contrib.auth.models import Group
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from fleet.models import (
    Driver,
    DriverStatus,
    FleetUserRole,
    TransportRequest,
    TransportRequestStatus,
    TripAllocation,
    TripAllocationStatus,
    TripLog,
    Vehicle,
    VehicleStatus,
)
from fleet.permissions import setup_fleet_permissions


@override_settings(NOTIFICATIONS_ENABLED=False)
class TripExecutionFlowTest(TestCase):
    """Covers start and completion lifecycle with mileage capture."""

    def setUp(self):
        setup_fleet_permissions()

        self.driver_user = User.objects.create_user(
            username="driver_phase6",
            password="testpass123",
            first_name="Jane",
            last_name="Driver",
        )
        driver_group = Group.objects.get(name=FleetUserRole.DRIVER)
        self.driver_user.groups.add(driver_group)

        requester = User.objects.create_user(
            username="requester_phase6",
            password="testpass123",
        )

        self.vehicle = Vehicle.objects.create(
            registration_number="PH6-001",
            make="Toyota",
            model="Hiace",
            vehicle_type="van",
            fuel_type="diesel",
            status=VehicleStatus.AVAILABLE,
        )

        self.driver = Driver.objects.create(
            user=self.driver_user,
            license_number="PH6-DL-001",
            license_expiry_date=timezone.now().date() + timedelta(days=365),
            status=DriverStatus.AVAILABLE,
        )

        departure = timezone.now() + timedelta(days=1)
        self.transport_request = TransportRequest.objects.create(
            requested_by=requester,
            activity_name="Phase 6 Trip",
            pickup_location="HQ",
            destination="Field Site",
            departure_datetime=departure,
            return_datetime=departure + timedelta(hours=6),
            num_passengers=3,
            justification="Execution flow test",
            status=TransportRequestStatus.APPROVED,
        )

        self.allocation = TripAllocation.objects.create(
            transport_request=self.transport_request,
            vehicle=self.vehicle,
            driver=self.driver,
            status=TripAllocationStatus.CONFIRMED,
            confirmed_by=self.driver_user,
            confirmed_at=timezone.now(),
        )
        self.transport_request.status = TransportRequestStatus.ALLOCATED
        self.transport_request.save()

        self.client.login(username="driver_phase6", password="testpass123")

    def test_start_trip_creates_trip_log_and_updates_statuses(self):
        response = self.client.post(
            reverse("fleet:start_trip", kwargs={"pk": self.allocation.pk}),
            data={"start_mileage": 120050},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)

        self.allocation.refresh_from_db()
        self.transport_request.refresh_from_db()
        self.vehicle.refresh_from_db()
        self.driver.refresh_from_db()

        self.assertEqual(self.allocation.status, TripAllocationStatus.IN_PROGRESS)
        self.assertEqual(self.transport_request.status, TransportRequestStatus.IN_PROGRESS)
        self.assertEqual(self.vehicle.status, VehicleStatus.BOOKED)
        self.assertEqual(self.driver.status, DriverStatus.ASSIGNED)

        trip_log = TripLog.objects.get(trip_allocation=self.allocation)
        self.assertEqual(trip_log.start_mileage, 120050)
        self.assertIsNone(trip_log.end_mileage)

    def test_complete_trip_updates_trip_log_and_restores_statuses(self):
        self.allocation.status = TripAllocationStatus.IN_PROGRESS
        self.allocation.actual_departure_datetime = timezone.now() - timedelta(hours=2)
        self.allocation.save()

        self.transport_request.status = TransportRequestStatus.IN_PROGRESS
        self.transport_request.save()

        self.vehicle.status = VehicleStatus.BOOKED
        self.vehicle.save(update_fields=["status"])
        self.driver.status = DriverStatus.ASSIGNED
        self.driver.save(update_fields=["status"])

        TripLog.objects.create(
            trip_allocation=self.allocation,
            start_mileage=5000,
            created_by=self.driver_user,
            updated_by=self.driver_user,
        )

        response = self.client.post(
            reverse("fleet:complete_trip", kwargs={"pk": self.allocation.pk}),
            data={
                "end_mileage": 5064,
                "actual_distance_km": "",
                "incident_notes": "Minor traffic delay",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)

        self.allocation.refresh_from_db()
        self.transport_request.refresh_from_db()
        self.vehicle.refresh_from_db()
        self.driver.refresh_from_db()

        trip_log = TripLog.objects.get(trip_allocation=self.allocation)

        self.assertEqual(self.allocation.status, TripAllocationStatus.COMPLETED)
        self.assertEqual(self.transport_request.status, TransportRequestStatus.COMPLETED)
        self.assertEqual(self.vehicle.status, VehicleStatus.AVAILABLE)
        self.assertEqual(self.driver.status, DriverStatus.AVAILABLE)
        self.assertEqual(trip_log.end_mileage, 5064)
        self.assertEqual(trip_log.distance, 64)
        self.assertEqual(trip_log.incident_notes, "Minor traffic delay")
        self.assertEqual(float(self.allocation.actual_distance_km), 64.0)
