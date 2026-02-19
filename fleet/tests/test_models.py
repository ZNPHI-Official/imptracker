"""
Fleet Management Model Tests - Phase 2

Comprehensive tests for all core models:
- Vehicle
- Driver
- TransportRequest
- TripAllocation
- TripLog
- MaintenanceRecord
- AuditLog

Coverage targets: Unit tests, validation, constraints, workflows, conflict detection
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, timedelta
import uuid

from accounts.models import User
from fleet.models import (
    Vehicle, Driver, TransportRequest, TripAllocation, TripLog,
    MaintenanceRecord, AuditLog,
    VehicleStatus, DriverStatus, TransportRequestStatus, TripAllocationStatus,
    AuditAction
)


class VehicleModelTest(TestCase):
    """Test Vehicle model."""
    
    def setUp(self):
        """Create test vehicle."""
        self.vehicle = Vehicle.objects.create(
            registration_number="ABC-123",
            make="Toyota",
            model="Hiace",
            vehicle_type="van",
            fuel_type="diesel",
            assigned_location="Main Depot",
            status=VehicleStatus.AVAILABLE
        )
    
    def test_vehicle_creation(self):
        """Test vehicle creation."""
        self.assertTrue(self.vehicle.pk)
        self.assertEqual(self.vehicle.registration_number, "ABC-123")
        self.assertEqual(self.vehicle.status, VehicleStatus.AVAILABLE)
    
    def test_registration_number_unique(self):
        """Test that registration numbers must be unique."""
        with self.assertRaises(Exception):
            Vehicle.objects.create(
                registration_number="ABC-123",
                make="Ford",
                model="Transit"
            )
    
    def test_vehicle_string_representation(self):
        """Test vehicle __str__ method."""
        expected = "ABC-123 (Toyota Hiace)"
        self.assertEqual(str(self.vehicle), expected)
    
    def test_maintenance_due_check(self):
        """Test maintenance due date checking."""
        # No maintenance yet
        self.assertFalse(self.vehicle.is_maintenance_due())
        
        # Set next service to past date
        self.vehicle.next_service_due = timezone.now().date() - timedelta(days=1)
        self.assertTrue(self.vehicle.is_maintenance_due())
    
    def test_service_date_validation(self):
        """Test that next service date must be after last service date."""
        today = timezone.now().date()
        
        self.vehicle.last_service_date = today
        self.vehicle.next_service_due = today - timedelta(days=1)
        
        with self.assertRaises(ValidationError):
            self.vehicle.clean()
    
    def test_vehicle_status_choices(self):
        """Test vehicle status field choices."""
        for status in [VehicleStatus.AVAILABLE, VehicleStatus.BOOKED, 
                       VehicleStatus.MAINTENANCE, VehicleStatus.OUT_OF_SERVICE]:
            v = Vehicle.objects.create(
                registration_number=f"VEH-{status}",
                status=status
            )
            self.assertEqual(v.status, status)


class DriverModelTest(TestCase):
    """Test Driver model."""
    
    def setUp(self):
        """Create test driver and user."""
        self.user = User.objects.create_user(
            username="driver1",
            first_name="John",
            last_name="Doe",
            password="testpass123"
        )
        
        self.driver = Driver.objects.create(
            user=self.user,
            license_number="DL-2024-001",
            phone_number="256-712-345678",
            license_expiry_date=timezone.now().date() + timedelta(days=365),
            status=DriverStatus.AVAILABLE
        )
    
    def test_driver_creation(self):
        """Test driver creation."""
        self.assertTrue(self.driver.pk)
        self.assertEqual(self.driver.user, self.user)
        self.assertEqual(self.driver.status, DriverStatus.AVAILABLE)
    
    def test_license_number_unique(self):
        """Test that license numbers must be unique."""
        user2 = User.objects.create_user(username="driver2")
        
        with self.assertRaises(Exception):
            Driver.objects.create(
                user=user2,
                license_number="DL-2024-001",
                license_expiry_date=timezone.now().date() + timedelta(days=365)
            )
    
    def test_driver_string_representation(self):
        """Test driver __str__ method."""
        expected = f"John Doe (DL-2024-001)"
        self.assertEqual(str(self.driver), expected)
    
    def test_license_expiry_validation(self):
        """Test that expired licenses are rejected."""
        user = User.objects.create_user(username="expired_driver")
        
        driver = Driver(
            user=user,
            license_number="DL-EXPIRED",
            license_expiry_date=timezone.now().date() - timedelta(days=1)
        )
        
        with self.assertRaises(ValidationError):
            driver.clean()
    
    def test_license_expires_soon(self):
        """Test license expiry warning."""
        # Expiry in 15 days
        self.driver.license_expiry_date = timezone.now().date() + timedelta(days=15)
        self.assertTrue(self.driver.license_expires_soon(days=30))
        self.assertFalse(self.driver.license_expires_soon(days=10))
    
    def test_driver_status_choices(self):
        """Test driver status field choices."""
        for status in [DriverStatus.AVAILABLE, DriverStatus.ASSIGNED, DriverStatus.ON_LEAVE]:
            user = User.objects.create_user(username=f"driver_{status}")
            d = Driver.objects.create(
                user=user,
                license_number=f"DL-{status}",
                status=status,
                license_expiry_date=timezone.now().date() + timedelta(days=365)
            )
            self.assertEqual(d.status, status)


class TransportRequestModelTest(TestCase):
    """Test TransportRequest model."""
    
    def setUp(self):
        """Create test request."""
        self.user = User.objects.create_user(username="requester1")
        
        tomorrow = timezone.now() + timedelta(days=1)
        next_day = tomorrow + timedelta(hours=8)
        
        self.request = TransportRequest.objects.create(
            requested_by=self.user,
            activity_name="Test Activity",
            pickup_location="Point A",
            destination="Point B",
            departure_datetime=tomorrow,
            return_datetime=next_day,
            num_passengers=5,
            justification="Test transport"
        )
    
    def test_request_creation(self):
        """Test transport request creation."""
        self.assertTrue(self.request.pk)
        self.assertEqual(self.request.status, TransportRequestStatus.DRAFT)
        self.assertIsNotNone(self.request.request_id)
        self.assertTrue(self.request.request_id.startswith("TR-"))
    
    def test_request_id_unique(self):
        """Test that request IDs are unique."""
        req1 = TransportRequest.objects.create(
            requested_by=self.user,
            activity_name="Request 1",
            pickup_location="A",
            destination="B",
            departure_datetime=timezone.now() + timedelta(days=1),
            return_datetime=timezone.now() + timedelta(days=2),
            justification="Test"
        )
        
        req2 = TransportRequest.objects.create(
            requested_by=self.user,
            activity_name="Request 2",
            pickup_location="A",
            destination="B",
            departure_datetime=timezone.now() + timedelta(days=3),
            return_datetime=timezone.now() + timedelta(days=4),
            justification="Test"
        )
        
        self.assertNotEqual(req1.request_id, req2.request_id)
    
    def test_return_datetime_validation(self):
        """Test that return datetime must be after departure."""
        now = timezone.now()
        self.request.return_datetime = self.request.departure_datetime - timedelta(hours=1)
        
        with self.assertRaises(ValidationError):
            self.request.clean()
    
    def test_past_datetime_validation(self):
        """Test that departure cannot be in past."""
        self.request.departure_datetime = timezone.now() - timedelta(hours=1)
        
        with self.assertRaises(ValidationError):
            self.request.clean()
    
    def test_status_transition_draft_to_pending(self):
        """Test status transition from Draft to Pending Approval."""
        self.request.status = TransportRequestStatus.PENDING_APPROVAL
        # Should not raise
        self.request.save()
    
    def test_invalid_status_transition(self):
        """Test that invalid transitions are rejected."""
        # First transition to PENDING_APPROVAL is valid
        self.request.status = TransportRequestStatus.PENDING_APPROVAL
        self.request.save()
        
        # Try invalid transition: PENDING_APPROVAL -> DRAFT
        self.request.status = TransportRequestStatus.DRAFT
        
        with self.assertRaises(ValidationError):
            self.request.save()
    
    def test_request_string_representation(self):
        """Test request __str__ method."""
        self.assertIn(self.request.request_id, str(self.request))
        self.assertIn("Test Activity", str(self.request))


class TripAllocationModelTest(TestCase):
    """Test TripAllocation model."""
    
    def setUp(self):
        """Create test allocation contexts."""
        # Create vehicle
        self.vehicle = Vehicle.objects.create(
            registration_number="VEH-001",
            status=VehicleStatus.AVAILABLE
        )
        
        # Create driver
        user = User.objects.create_user(username="driver_test")
        self.driver = Driver.objects.create(
            user=user,
            license_number="DL-TEST-001",
            license_expiry_date=timezone.now().date() + timedelta(days=365),
            status=DriverStatus.AVAILABLE
        )
        
        # Create user and request
        requester = User.objects.create_user(username="requester_test")
        tomorrow = timezone.now() + timedelta(days=1)
        self.request = TransportRequest.objects.create(
            requested_by=requester,
            activity_name="Test Trip",
            pickup_location="A",
            destination="B",
            departure_datetime=tomorrow,
            return_datetime=tomorrow + timedelta(hours=8),
            justification="Test",
            status=TransportRequestStatus.APPROVED
        )
    
    def test_allocation_creation(self):
        """Test allocation creation."""
        allocation = TripAllocation.objects.create(
            transport_request=self.request,
            vehicle=self.vehicle,
            driver=self.driver
        )
        
        self.assertTrue(allocation.pk)
        self.assertEqual(allocation.status, TripAllocationStatus.ALLOCATED)
    
    def test_allocation_requires_approved_request(self):
        """Test that request must be approved before allocation."""
        # Create a request that is NOT approved
        tomorrow = timezone.now() + timedelta(days=1)
        pending_request = TransportRequest.objects.create(
            requested_by=self.request.requested_by,
            activity_name="Pending Trip",
            pickup_location="A",
            destination="B",
            departure_datetime=tomorrow,
            return_datetime=tomorrow + timedelta(hours=8),
            justification="Test",
            status=TransportRequestStatus.PENDING_APPROVAL
        )
        
        allocation = TripAllocation(
            transport_request=pending_request,
            vehicle=self.vehicle,
            driver=self.driver
        )
        
        with self.assertRaises(ValidationError):
            allocation.save()
    
    def test_allocation_requires_available_vehicle(self):
        """Test that vehicle must be available."""
        # Create a maintenance vehicle
        maint_vehicle = Vehicle.objects.create(
            registration_number="VEH-MAINT",
            status=VehicleStatus.MAINTENANCE
        )
        
        allocation = TripAllocation(
            transport_request=self.request,
            vehicle=maint_vehicle,
            driver=self.driver
        )
        
        with self.assertRaises(ValidationError):
            allocation.save()
    
    def test_allocation_requires_available_driver(self):
        """Test that driver must be available."""
        # Create an on-leave driver
        on_leave_user = User.objects.create_user(username="driver_leave")
        on_leave_driver = Driver.objects.create(
            user=on_leave_user,
            license_number="DL-LEAVE-001",
            license_expiry_date=timezone.now().date() + timedelta(days=365),
            status=DriverStatus.ON_LEAVE
        )
        
        allocation = TripAllocation(
            transport_request=self.request,
            vehicle=self.vehicle,
            driver=on_leave_driver
        )
        
        with self.assertRaises(ValidationError):
            allocation.save()
    
    def test_vehicle_conflict_detection(self):
        """Test that vehicle conflicts are detected."""
        # Create first allocation with overlapping time
        allocation1 = TripAllocation.objects.create(
            transport_request=self.request,
            vehicle=self.vehicle,
            driver=self.driver,
            status=TripAllocationStatus.IN_PROGRESS
        )
        
        # Create second request with same time period (guaranteed overlap)
        # self.request goes from tomorrow 00:00 to tomorrow 08:00
        # Create request2 from tomorrow 01:00 to tomorrow 07:00 (definitely overlaps)
        tomorrow = timezone.now() + timedelta(days=1)
        request2 = TransportRequest.objects.create(
            requested_by=self.request.requested_by,
            activity_name="Conflicting Trip",
            pickup_location="A",
            destination="B",
            departure_datetime=tomorrow + timedelta(hours=1),
            return_datetime=tomorrow + timedelta(hours=7),
            justification="Test",
            status=TransportRequestStatus.APPROVED
        )
        
        # Create new driver to avoid driver conflict
        user2 = User.objects.create_user(username="driver_test2")
        driver2 = Driver.objects.create(
            user=user2,
            license_number="DL-TEST-002",
            license_expiry_date=timezone.now().date() + timedelta(days=365),
            status=DriverStatus.AVAILABLE
        )
        
        # Try to allocate same vehicle to overlapping time - should fail
        allocation2 = TripAllocation(
            transport_request=request2,
            vehicle=self.vehicle,
            driver=driver2
        )
        
        with self.assertRaises(ValidationError):
            allocation2.save()
    
    def test_driver_conflict_detection(self):
        """Test that driver conflicts are detected."""
        # Create first allocation with overlapping time
        allocation1 = TripAllocation.objects.create(
            transport_request=self.request,
            vehicle=self.vehicle,
            driver=self.driver,
            status=TripAllocationStatus.IN_PROGRESS
        )
        
        # Create second request with same time period (guaranteed overlap)
        # self.request goes from tomorrow 00:00 to tomorrow 08:00
        # Create request2 from tomorrow 01:00 to tomorrow 07:00 (definitely overlaps)
        tomorrow = timezone.now() + timedelta(days=1)
        request2 = TransportRequest.objects.create(
            requested_by=self.request.requested_by,
            activity_name="Conflicting Trip",
            pickup_location="A",
            destination="B",
            departure_datetime=tomorrow + timedelta(hours=1),
            return_datetime=tomorrow + timedelta(hours=7),
            justification="Test",
            status=TransportRequestStatus.APPROVED
        )
        
        # Create new vehicle to avoid vehicle conflict
        vehicle2 = Vehicle.objects.create(
            registration_number="VEH-002",
            status=VehicleStatus.AVAILABLE
        )
        
        # Try to allocate same driver to overlapping time - should fail
        allocation2 = TripAllocation(
            transport_request=request2,
            vehicle=vehicle2,
            driver=self.driver
        )
        
        with self.assertRaises(ValidationError):
            allocation2.save()


class TripLogModelTest(TestCase):
    """Test TripLog model."""
    
    def setUp(self):
        """Create test trip log context."""
        # Create vehicle and driver
        self.vehicle = Vehicle.objects.create(registration_number="VEH-LOG-001")
        user = User.objects.create_user(username="driver_log")
        self.driver = Driver.objects.create(
            user=user,
            license_number="DL-LOG-001",
            license_expiry_date=timezone.now().date() + timedelta(days=365)
        )
        
        # Create request and allocation
        requester = User.objects.create_user(username="req_log")
        tomorrow = timezone.now() + timedelta(days=1)
        self.request = TransportRequest.objects.create(
            requested_by=requester,
            activity_name="Log Test",
            pickup_location="A",
            destination="B",
            departure_datetime=tomorrow,
            return_datetime=tomorrow + timedelta(hours=8),
            justification="Test",
            status=TransportRequestStatus.APPROVED
        )
        
        self.allocation = TripAllocation.objects.create(
            transport_request=self.request,
            vehicle=self.vehicle,
            driver=self.driver
        )
    
    def test_trip_log_creation(self):
        """Test trip log creation."""
        log = TripLog.objects.create(
            trip_allocation=self.allocation,
            start_mileage=1000
        )
        
        self.assertTrue(log.pk)
        self.assertEqual(log.start_mileage, 1000)
        self.assertIsNone(log.end_mileage)
        self.assertIsNone(log.distance)
    
    def test_end_mileage_validation(self):
        """Test that end mileage must be greater than start."""
        log = TripLog(
            trip_allocation=self.allocation,
            start_mileage=1000,
            end_mileage=950
        )
        
        with self.assertRaises(ValidationError):
            log.clean()
    
    def test_distance_auto_calculation(self):
        """Test that distance is auto-calculated."""
        log = TripLog.objects.create(
            trip_allocation=self.allocation,
            start_mileage=1000
        )
        
        self.assertIsNone(log.distance)
        
        log.end_mileage = 1050
        log.save()
        
        log.refresh_from_db()
        self.assertEqual(log.distance, 50)
    
    def test_trip_completion_check(self):
        """Test is_complete() method."""
        log = TripLog.objects.create(
            trip_allocation=self.allocation,
            start_mileage=1000
        )
        
        self.assertFalse(log.is_complete())
        
        log.end_mileage = 1100
        log.save()
        
        self.assertTrue(log.is_complete())


class MaintenanceRecordModelTest(TestCase):
    """Test MaintenanceRecord model."""
    
    def setUp(self):
        """Create test vehicle."""
        self.vehicle = Vehicle.objects.create(
            registration_number="VEH-MAINT-001"
        )
    
    def test_maintenance_record_creation(self):
        """Test maintenance record creation."""
        today = timezone.now().date()
        record = MaintenanceRecord.objects.create(
            vehicle=self.vehicle,
            service_type="routine",
            service_date=today,
            next_due_date=today + timedelta(days=90)
        )
        
        self.assertTrue(record.pk)
        self.assertEqual(record.service_type, "routine")
    
    def test_next_due_date_validation(self):
        """Test that next due date must be after service date."""
        today = timezone.now().date()
        
        record = MaintenanceRecord(
            vehicle=self.vehicle,
            service_date=today,
            next_due_date=today - timedelta(days=1)
        )
        
        with self.assertRaises(ValidationError):
            record.clean()
    
    def test_maintenance_string_representation(self):
        """Test maintenance __str__ method."""
        today = timezone.now().date()
        record = MaintenanceRecord.objects.create(
            vehicle=self.vehicle,
            service_type="routine",
            service_date=today,
            next_due_date=today + timedelta(days=90)
        )
        
        self.assertIn(self.vehicle.registration_number, str(record))
        self.assertIn("Routine Service", str(record))


class AuditLogModelTest(TestCase):
    """Test AuditLog model."""
    
    def setUp(self):
        """Create test user and request."""
        self.user = User.objects.create_user(username="auditor")
        
        self.requester = User.objects.create_user(username="req_audit")
        tomorrow = timezone.now() + timedelta(days=1)
        self.request = TransportRequest.objects.create(
            requested_by=self.requester,
            activity_name="Audit Test",
            pickup_location="A",
            destination="B",
            departure_datetime=tomorrow,
            return_datetime=tomorrow + timedelta(hours=8),
            justification="Test"
        )
    
    def test_audit_log_creation(self):
        """Test audit log creation."""
        log = AuditLog.objects.create(
            action=AuditAction.REQUEST_CREATED,
            transport_request=self.request,
            performed_by=self.user,
            notes="Initial creation"
        )
        
        self.assertTrue(log.pk)
        self.assertEqual(log.action, AuditAction.REQUEST_CREATED)
        self.assertIsNotNone(log.timestamp)
    
    def test_audit_log_immutability(self):
        """Test that audit logs cannot be modified (deletion check)."""
        log = AuditLog.objects.create(
            action=AuditAction.REQUEST_CREATED,
            transport_request=self.request,
            performed_by=self.user
        )
        
        # Try to delete - should fail
        with self.assertRaises(ValidationError):
            log.delete()
    
    def test_audit_log_undeletable(self):
        """Test that audit logs cannot be deleted."""
        log = AuditLog.objects.create(
            action=AuditAction.REQUEST_CREATED,
            transport_request=self.request,
            performed_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            log.delete()
    
    def test_audit_log_string_representation(self):
        """Test audit log __str__ method."""
        log = AuditLog.objects.create(
            action=AuditAction.REQUEST_APPROVED,
            transport_request=self.request,
            performed_by=self.user
        )
        
        self.assertIn(AuditAction.REQUEST_APPROVED, str(log))
        self.assertIn(self.user.username, str(log))


class ModelConstraintsTest(TestCase):
    """Test database constraints and relationships."""
    
    def setUp(self):
        """Create base objects."""
        self.vehicle = Vehicle.objects.create(registration_number="VEH-CONST-001")
        user = User.objects.create_user(username="dr_const")
        self.driver = Driver.objects.create(
            user=user,
            license_number="DL-CONST-001",
            license_expiry_date=timezone.now().date() + timedelta(days=365)
        )
    
    def test_vehicle_cascade_on_allocation_delete(self):
        """Test that deleting vehicle protects allocations."""
        requester = User.objects.create_user(username="req_const")
        tomorrow = timezone.now() + timedelta(days=1)
        request = TransportRequest.objects.create(
            requested_by=requester,
            activity_name="Test",
            pickup_location="A",
            destination="B",
            departure_datetime=tomorrow,
            return_datetime=tomorrow + timedelta(hours=8),
            justification="Test",
            status=TransportRequestStatus.APPROVED
        )
        
        allocation = TripAllocation.objects.create(
            transport_request=request,
            vehicle=self.vehicle,
            driver=self.driver
        )
        
        # Try to delete vehicle - should fail
        with self.assertRaises(Exception):
            self.vehicle.delete()
    
    def test_user_cascade_on_driver_deletion(self):
        """Test driver deletion when user is deleted."""
        driver_user = User.objects.create_user(username="dr_del")
        driver = Driver.objects.create(
            user=driver_user,
            license_number="DL-DEL-001",
            license_expiry_date=timezone.now().date() + timedelta(days=365)
        )
        
        # Delete user
        driver_user.delete()
        
        # Driver should also be deleted
        self.assertFalse(Driver.objects.filter(pk=driver.pk).exists())
    
    def test_request_one_to_one_allocation(self):
        """Test one-to-one relationship between request and allocation."""
        requester = User.objects.create_user(username="req_one")
        tomorrow = timezone.now() + timedelta(days=1)
        request = TransportRequest.objects.create(
            requested_by=requester,
            activity_name="Test",
            pickup_location="A",
            destination="B",
            departure_datetime=tomorrow,
            return_datetime=tomorrow + timedelta(hours=8),
            justification="Test",
            status=TransportRequestStatus.APPROVED
        )
        
        allocation1 = TripAllocation.objects.create(
            transport_request=request,
            vehicle=self.vehicle,
            driver=self.driver
        )
        
        # Try to create second allocation - should fail
        user2 = User.objects.create_user(username="dr_const2")
        driver2 = Driver.objects.create(
            user=user2,
            license_number="DL-CONST-002",
            license_expiry_date=timezone.now().date() + timedelta(days=365)
        )
        
        with self.assertRaises(Exception):
            TripAllocation.objects.create(
                transport_request=request,
                vehicle=self.vehicle,
                driver=driver2
            )
