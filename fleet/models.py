"""
Fleet Management Models

Core data models for the Fleet Management module including:
- Vehicle: Fleet asset management
- Driver: Personnel management
- TransportRequest: Request submission for trips
- TripAllocation: Vehicle + Driver assignment
- TripLog: Trip execution record
- MaintenanceRecord: Service tracking
- AuditLog: Immutable audit trail
"""

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, timedelta
import uuid

from accounts.models import User


# ============================================================================
# CHOICE FIELDS
# ============================================================================

class VehicleStatus(models.TextChoices):
    """Vehicle availability status choices."""
    AVAILABLE = "available", "Available"
    BOOKED = "booked", "Booked"
    MAINTENANCE = "maintenance", "Maintenance"
    OUT_OF_SERVICE = "out_of_service", "Out of Service"


class DriverStatus(models.TextChoices):
    """Driver availability status choices."""
    AVAILABLE = "available", "Available"
    ASSIGNED = "assigned", "Assigned"
    ON_LEAVE = "on_leave", "On Leave"


class TransportRequestStatus(models.TextChoices):
    """Transport request workflow status."""
    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending Approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    ALLOCATED = "allocated", "Allocated"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class JourneyType(models.TextChoices):
    """Journey type choices for transport requests."""
    LINKED = "linked", "Linked to Activity"
    AD_HOC = "ad_hoc", "Ad-hoc Request"


class TripAllocationStatus(models.TextChoices):
    """Trip allocation execution status."""
    ALLOCATED = "allocated", "Allocated"
    CONFIRMED = "confirmed", "Confirmed"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class AuditAction(models.TextChoices):
    """Types of actions logged in audit trail."""
    REQUEST_CREATED = "request_created", "Request Created"
    REQUEST_APPROVED = "request_approved", "Request Approved"
    REQUEST_REJECTED = "request_rejected", "Request Rejected"
    TRIP_ALLOCATED = "trip_allocated", "Trip Allocated"
    DRIVER_CONFIRMED = "driver_confirmed", "Driver Confirmed"
    TRIP_STARTED = "trip_started", "Trip Started"
    TRIP_COMPLETED = "trip_completed", "Trip Completed"
    TRIP_CANCELLED = "trip_cancelled", "Trip Cancelled"
    ALLOCATION_MODIFIED = "allocation_modified", "Allocation Modified"


# ============================================================================
# BASE MIXIN
# ============================================================================

class FleetAuditMixin(models.Model):
    """
    Base mixin for audit trail and tracking on all fleet models.
    Provides created_at, updated_at, created_by, updated_by fields.
    """
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="%(class)s_created",
        editable=False,
        null=True,
        blank=True
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="%(class)s_updated",
        editable=False,
        null=True,
        blank=True
    )

    class Meta:
        abstract = True


# ============================================================================
# VEHICLE MODEL
# ============================================================================

class Vehicle(FleetAuditMixin):
    """
    Vehicle model for fleet asset management.
    
    Constraints:
    - Registration number must be unique
    - Only Available vehicles can be allocated
    """
    
    FUEL_TYPES = [
        ("petrol", "Petrol"),
        ("diesel", "Diesel"),
        ("electric", "Electric"),
        ("hybrid", "Hybrid"),
    ]
    
    VEHICLE_TYPES = [
        ("sedan", "Sedan"),
        ("suv", "SUV"),
        ("van", "Van"),
        ("truck", "Truck"),
        ("minibus", "Minibus"),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique vehicle registration number"
    )
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    vehicle_type = models.CharField(
        max_length=20,
        choices=VEHICLE_TYPES,
        default="van"
    )
    fuel_type = models.CharField(
        max_length=20,
        choices=FUEL_TYPES,
        default="diesel"
    )
    status = models.CharField(
        max_length=20,
        choices=VehicleStatus.choices,
        default=VehicleStatus.AVAILABLE,
        db_index=True,
        help_text="Current availability status"
    )
    assigned_location = models.CharField(
        max_length=255,
        blank=True,
        help_text="Location where vehicle is based"
    )
    last_service_date = models.DateField(null=True, blank=True)
    next_service_due = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether vehicle is in service"
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ["registration_number"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["status", "is_active"]),
        ]
        verbose_name_plural = "Vehicles"
    
    def __str__(self):
        return f"{self.registration_number} ({self.make} {self.model})"
    
    def clean(self):
        """Validate vehicle data."""
        if self.last_service_date and self.next_service_due:
            if self.next_service_due <= self.last_service_date:
                raise ValidationError(
                    "Next service date must be after last service date"
                )
    
    def is_maintenance_due(self):
        """Check if vehicle is due for maintenance."""
        if not self.next_service_due:
            return False
        return self.next_service_due <= timezone.now().date()
    
    def has_allocation_conflict(self, start_dt, end_dt):
        """
        Check if vehicle has conflicting allocation in date/time range.
        
        Args:
            start_dt: Start datetime
            end_dt: End datetime
        
        Returns:
            bool: True if conflict exists
        """
        conflicts = TripAllocation.objects.filter(
            vehicle=self,
            status__in=[
                TripAllocationStatus.ALLOCATED,
                TripAllocationStatus.CONFIRMED,
                TripAllocationStatus.IN_PROGRESS,
            ],
            transport_request__departure_datetime__lt=end_dt,
            transport_request__return_datetime__gt=start_dt,
        ).exists()
        return conflicts


# ============================================================================
# DRIVER MODEL
# ============================================================================

class Driver(FleetAuditMixin):
    """
    Driver model for personnel management.
    
    Extends User model with driver-specific fields.
    One-to-one relationship with User for authentication.
    """
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="driver_profile",
        help_text="Associated user account"
    )
    license_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique driver license number"
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Driver contact phone"
    )
    license_expiry_date = models.DateField(
        help_text="Driver license expiry date"
    )
    status = models.CharField(
        max_length=20,
        choices=DriverStatus.choices,
        default=DriverStatus.AVAILABLE,
        db_index=True
    )
    assigned_location = models.CharField(
        max_length=255,
        blank=True,
        help_text="Location where driver is based"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True
    )
    hired_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ["user__first_name", "user__last_name"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["status", "is_active"]),
        ]
    
    def __str__(self):
        return f"{self.user.get_full_name()} ({self.license_number})"
    
    def clean(self):
        """Validate driver data."""
        if self.license_expiry_date <= timezone.now().date():
            raise ValidationError("Driver license has expired")
    
    def license_expires_soon(self, days=30):
        """Check if license expires within specified days."""
        expiry_threshold = timezone.now().date() + timedelta(days=days)
        return self.license_expiry_date <= expiry_threshold
    
    def has_allocation_conflict(self, start_dt, end_dt):
        """
        Check if driver has conflicting allocation in date/time range.
        
        Args:
            start_dt: Start datetime
            end_dt: End datetime
        
        Returns:
            bool: True if conflict exists
        """
        conflicts = TripAllocation.objects.filter(
            driver=self,
            status__in=[
                TripAllocationStatus.ALLOCATED,
                TripAllocationStatus.CONFIRMED,
                TripAllocationStatus.IN_PROGRESS,
            ],
            transport_request__departure_datetime__lt=end_dt,
            transport_request__return_datetime__gt=start_dt,
        ).exists()
        return conflicts


# ============================================================================
# TRANSPORT REQUEST MODEL
# ============================================================================

class TransportRequest(FleetAuditMixin):
    """
    Transport request model for trip requests.
    
    Can be linked to an existing Activity or be standalone (ad-hoc).
    Constraints:
    - Request ID must be unique (auto-generated)
    - Status transitions must follow defined workflow
    """
    
    # Auto-generated unique request ID
    request_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated request identifier"
    )
    
    # Linking to existing activity (optional)
    from activities.models import Activity
    linked_activity = models.ForeignKey(
        Activity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transport_requests",
        help_text="Linked implementation activity (optional)"
    )
    
    # Request metadata
    requested_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="transport_requests"
    )
    status = models.CharField(
        max_length=20,
        choices=TransportRequestStatus.choices,
        default=TransportRequestStatus.DRAFT,
        db_index=True
    )
    
    # Activity details
    activity_name = models.CharField(
        max_length=255,
        help_text="Name of the activity/trip"
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of transport need"
    )
    
    # Location details
    pickup_location = models.CharField(
        max_length=255,
        help_text="Pickup location address"
    )
    destination = models.CharField(
        max_length=255,
        help_text="Destination address"
    )
    
    # Time details
    departure_datetime = models.DateTimeField(
        help_text="Planned departure date and time"
    )
    return_datetime = models.DateTimeField(
        help_text="Planned return date and time"
    )
    
    # Trip details
    num_passengers = models.PositiveIntegerField(
        default=1,
        help_text="Number of passengers"
    )
    justification = models.TextField(
        help_text="Justification for transport request"
    )
    special_requirements = models.TextField(
        blank=True,
        help_text="Any special requirements (e.g., wheelchair access, equipment space)"
    )
    
    # Rejection reason (if applicable)
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejection (if rejected)"
    )
    
    # Approval details
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_transport_requests",
        help_text="User who approved the request"
    )
    approval_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date/time of approval"
    )
    
    class Meta:
        ordering = ["-departure_datetime"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["requested_by"]),
            models.Index(fields=["departure_datetime"]),
            models.Index(fields=["status", "departure_datetime"]),
            models.Index(fields=["return_datetime"]),
            models.Index(fields=["departure_datetime", "return_datetime"]),
        ]
    
    def __str__(self):
        return f"{self.request_id} - {self.activity_name}"
    
    def clean(self):
        """Validate request data."""
        if self.return_datetime <= self.departure_datetime:
            raise ValidationError(
                "Return datetime must be after departure datetime"
            )
        
        if self.departure_datetime < timezone.now():
            raise ValidationError(
                "Departure datetime cannot be in the past"
            )
        
        if self.num_passengers < 1:
            raise ValidationError(
                "Number of passengers must be at least 1"
            )
        
        # Validate status transitions
        if self.pk:  # Only validate transitions on existing requests
            old_request = TransportRequest.objects.get(pk=self.pk)
            valid_transitions = {
                TransportRequestStatus.DRAFT: [
                    TransportRequestStatus.PENDING_APPROVAL,
                    TransportRequestStatus.CANCELLED,
                ],
                TransportRequestStatus.PENDING_APPROVAL: [
                    TransportRequestStatus.APPROVED,
                    TransportRequestStatus.REJECTED,
                    TransportRequestStatus.CANCELLED,
                ],
                TransportRequestStatus.APPROVED: [
                    TransportRequestStatus.ALLOCATED,
                    TransportRequestStatus.CANCELLED,
                ],
                TransportRequestStatus.ALLOCATED: [
                    TransportRequestStatus.IN_PROGRESS,
                    TransportRequestStatus.CANCELLED,
                ],
                TransportRequestStatus.IN_PROGRESS: [
                    TransportRequestStatus.COMPLETED,
                    TransportRequestStatus.CANCELLED,
                ],
                TransportRequestStatus.REJECTED: [],
                TransportRequestStatus.COMPLETED: [],
                TransportRequestStatus.CANCELLED: [],
            }
            
            if self.status not in valid_transitions.get(
                old_request.status, []
            ):
                raise ValidationError(
                    f"Cannot transition from {old_request.status} to {self.status}"
                )
    
    def generate_request_id(self):
        """
        Generate unique request ID if not already set.
        Format: TR-YYYYMMDD-XXXXX (e.g., TR-20260219-00001)
        """
        if not self.request_id:
            today = timezone.now().strftime("%Y%m%d")
            count = TransportRequest.objects.filter(
                request_id__startswith=f"TR-{today}"
            ).count() + 1
            self.request_id = f"TR-{today}-{count:05d}"
    
    def save(self, *args, **kwargs):
        """Auto-generate request_id and validate before saving."""
        self.generate_request_id()
        self.clean()
        super().save(*args, **kwargs)


# ============================================================================
# TRIP ALLOCATION MODEL
# ============================================================================

class TripAllocation(FleetAuditMixin):
    """
    Trip allocation model for vehicle + driver assignment.
    
    Constraints:
    - No overlapping allocations for same vehicle/driver
    - Vehicle and driver must be available
    - Request must be in Approved status before allocation
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transport_request = models.OneToOneField(
        TransportRequest,
        on_delete=models.CASCADE,
        related_name="trip_allocation"
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="allocations"
    )
    driver = models.ForeignKey(
        Driver,
        on_delete=models.PROTECT,
        related_name="allocations"
    )
    status = models.CharField(
        max_length=20,
        choices=TripAllocationStatus.choices,
        default=TripAllocationStatus.ALLOCATED,
        db_index=True
    )
    
    # Confirmation tracking
    confirmed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_allocations",
        help_text="Driver who confirmed this allocation"
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When driver confirmed this allocation"
    )
    
    # Actual trip execution times
    actual_departure_datetime = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Actual time when trip started"
    )
    actual_return_datetime = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Actual time when trip completed"
    )
    actual_distance_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual distance traveled in km"
    )
    
    # Allocation notes
    allocation_notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["vehicle", "status"]),
            models.Index(fields=["driver", "status"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            # Performance indexes for allocation queries
            models.Index(fields=["transport_request", "status"]),
        ]
    
    def __str__(self):
        return f"{self.transport_request.request_id} - {self.vehicle.registration_number}"
    
    def clean(self):
        """Validate allocation constraints."""
        if self._state.adding:  # New allocation
            # Check request status
            if self.transport_request.status != TransportRequestStatus.APPROVED:
                raise ValidationError(
                    f"Request must be Approved, not {self.transport_request.status}"
                )
            
            # Check vehicle availability
            if self.vehicle.status != VehicleStatus.AVAILABLE:
                raise ValidationError(
                    f"Vehicle {self.vehicle.registration_number} is not available"
                )
            
            # Check driver availability
            if self.driver.status != DriverStatus.AVAILABLE:
                raise ValidationError(
                    f"Driver {self.driver.user.get_full_name()} is not available"
                )
            
            # Check vehicle conflicts
            if self.vehicle.has_allocation_conflict(
                self.transport_request.departure_datetime,
                self.transport_request.return_datetime,
            ):
                raise ValidationError(
                    f"Vehicle {self.vehicle.registration_number} has conflicting allocation"
                )
            
            # Check driver conflicts
            if self.driver.has_allocation_conflict(
                self.transport_request.departure_datetime,
                self.transport_request.return_datetime,
            ):
                raise ValidationError(
                    f"Driver {self.driver.user.get_full_name()} has conflicting allocation"
                )
    
    def get_conflicting_allocations(self):
        """
        Get list of allocations that conflict with this one.
        Useful for reporting reasons for allocation rejection.
        """
        vehicle_conflicts = TripAllocation.objects.filter(
            vehicle=self.vehicle,
            status__in=[
                TripAllocationStatus.ALLOCATED,
                TripAllocationStatus.CONFIRMED,
                TripAllocationStatus.IN_PROGRESS,
            ],
            transport_request__departure_datetime__lt=self.transport_request.return_datetime,
            transport_request__return_datetime__gt=self.transport_request.departure_datetime,
        ).exclude(pk=self.pk)
        
        driver_conflicts = TripAllocation.objects.filter(
            driver=self.driver,
            status__in=[
                TripAllocationStatus.ALLOCATED,
                TripAllocationStatus.CONFIRMED,
                TripAllocationStatus.IN_PROGRESS,
            ],
            transport_request__departure_datetime__lt=self.transport_request.return_datetime,
            transport_request__return_datetime__gt=self.transport_request.departure_datetime,
        ).exclude(pk=self.pk)
        
        return list(vehicle_conflicts) + list(driver_conflicts)
    
    def save(self, *args, **kwargs):
        """Validate before saving."""
        self.clean()
        super().save(*args, **kwargs)


# ============================================================================
# TRIP LOG MODEL
# ============================================================================

class TripLog(FleetAuditMixin):
    """
    Trip log model for recording execution details.
    
    Constraints:
    - End mileage must be greater than start mileage
    - Distance auto-calculated
    - Both mileage readings required before completion
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip_allocation = models.OneToOneField(
        TripAllocation,
        on_delete=models.CASCADE,
        related_name="trip_log"
    )
    
    # Mileage tracking
    start_mileage = models.PositiveIntegerField(
        help_text="Odometer reading at start (in km)"
    )
    end_mileage = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Odometer reading at end (in km)"
    )
    distance = models.PositiveIntegerField(
        null=True,
        blank=True,
        editable=False,
        help_text="Calculated distance (end - start)"
    )
    
    # Trip execution details
    start_datetime = models.DateTimeField(
        auto_now_add=True,
        help_text="When trip recording was started"
    )
    end_datetime = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When trip was completed"
    )
    
    # Incident tracking
    incident_notes = models.TextField(
        blank=True,
        help_text="Any incidents or issues during trip"
    )
    
    class Meta:
        ordering = ["-start_datetime"]
        indexes = [
            models.Index(fields=["trip_allocation"]),
            models.Index(fields=["start_datetime"]),
        ]
    
    def __str__(self):
        return f"Trip Log - {self.trip_allocation.transport_request.request_id}"
    
    def clean(self):
        """Validate trip log data."""
        if self.end_mileage is not None:
            if self.end_mileage <= self.start_mileage:
                raise ValidationError(
                    "End mileage must be greater than start mileage"
                )
    
    def save(self, *args, **kwargs):
        """Validate and auto-calculate distance before saving."""
        self.clean()
        if self.end_mileage is not None:
            self.distance = self.end_mileage - self.start_mileage
        super().save(*args, **kwargs)
    
    def is_complete(self):
        """Check if trip log has all required information."""
        return self.end_mileage is not None and self.distance is not None


# ============================================================================
# MAINTENANCE RECORD MODEL
# ============================================================================

class MaintenanceRecord(FleetAuditMixin):
    """
    Maintenance record model for vehicle service tracking.
    """
    
    MAINTENANCE_TYPES = [
        ("routine", "Routine Service"),
        ("repair", "Repair"),
        ("inspection", "Inspection"),
        ("tire_change", "Tire Change"),
        ("oil_change", "Oil Change"),
        ("other", "Other"),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="maintenance_records"
    )
    
    service_type = models.CharField(
        max_length=20,
        choices=MAINTENANCE_TYPES,
        default="routine"
    )
    service_date = models.DateField(
        help_text="Date service was performed"
    )
    next_due_date = models.DateField(
        help_text="Date next service is due"
    )
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Cost of service in currency"
    )
    
    # Service details
    service_provider = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of workshop/service provider"
    )
    mileage_at_service = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Vehicle mileage at time of service"
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ["-service_date"]
        indexes = [
            models.Index(fields=["vehicle", "service_date"]),
            models.Index(fields=["next_due_date"]),
        ]
    
    def __str__(self):
        return f"{self.vehicle.registration_number} - {self.get_service_type_display()}"
    
    def clean(self):
        """Validate maintenance record."""
        if self.next_due_date <= self.service_date:
            raise ValidationError(
                "Next service due date must be after service date"
            )
    
    def save(self, *args, **kwargs):
        """Validate before saving."""
        self.clean()
        super().save(*args, **kwargs)


# ============================================================================
# AUDIT LOG MODEL
# ============================================================================

class AuditLog(models.Model):
    """
    Immutable audit trail for all significant fleet actions.
    
    Constraints:
    - Records are never deleted or modified
    - All state changes automatically logged
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # What action occurred
    action = models.CharField(
        max_length=50,
        choices=AuditAction.choices,
        db_index=True
    )
    
    # What was affected
    transport_request = models.ForeignKey(
        TransportRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_logs"
    )
    trip_allocation = models.ForeignKey(
        TripAllocation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_logs"
    )
    
    # Who did it
    performed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="fleet_audit_logs"
    )
    
    # When it happened
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Additional context
    notes = models.TextField(blank=True)
    old_value = models.TextField(blank=True, help_text="Previous value (if modification)")
    new_value = models.TextField(blank=True, help_text="New value (if modification)")
    
    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["action", "timestamp"]),
            models.Index(fields=["performed_by", "timestamp"]),
        ]
    
    def __str__(self):
        return f"{self.action} by {self.performed_by} at {self.timestamp}"
    
    def save(self, *args, **kwargs):
        """Save audit log (creation is allowed, modification prevention handled elsewhere)."""
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        """Prevent deletion of audit logs."""
        raise ValidationError("Audit logs cannot be deleted")


# ============================================================================
# PERMISSION DEFINITIONS (used by permissions.py)
# ============================================================================

class FleetPermission:
    """
    Centralized definition of all fleet-related permissions.
    Used for group setup and permission checks.
    """
    
    # Transport Request permissions
    REQUEST_CREATE = "fleet.add_transportrequest"
    REQUEST_VIEW_OWN = "fleet.view_own_requests"
    REQUEST_VIEW_ALL = "fleet.view_all_requests"
    REQUEST_EDIT_OWN = "fleet.edit_own_requests"
    REQUEST_CANCEL = "fleet.cancel_request"
    REQUEST_DELETE = "fleet.delete_transportrequest"
    
    # Approval permissions
    REQUEST_APPROVE = "fleet.approve_request"
    REQUEST_REJECT = "fleet.reject_request"
    
    # Allocation permissions
    ALLOCATION_CREATE = "fleet.add_tripallocation"
    ALLOCATION_VIEW = "fleet.view_tripallocation"
    ALLOCATION_MODIFY = "fleet.modify_tripallocation"
    ALLOCATION_DELETE = "fleet.delete_tripallocation"
    
    # Trip execution permissions
    TRIP_CONFIRM = "fleet.confirm_trip"
    TRIP_UPDATE_STATUS = "fleet.update_trip_status"
    TRIP_COMPLETE = "fleet.complete_trip"
    TRIP_LOG = "fleet.add_triplog"
    
    # Master data permissions
    VEHICLE_MANAGE = "fleet.manage_vehicle"
    DRIVER_MANAGE = "fleet.manage_driver"
    MAINTENANCE_MANAGE = "fleet.manage_maintenance"
    
    # Dashboard permissions
    DASHBOARD_VIEW = "fleet.view_fleet_dashboard"
    DASHBOARD_MANAGE = "fleet.manage_fleet_dashboard"
    
    # Audit permissions
    AUDIT_VIEW = "fleet.view_auditlog"
    
    @classmethod
    def get_all_permissions(cls):
        """Return list of all custom permission strings."""
        return [
            # Request permissions
            cls.REQUEST_CREATE,
            cls.REQUEST_VIEW_OWN,
            cls.REQUEST_VIEW_ALL,
            cls.REQUEST_EDIT_OWN,
            cls.REQUEST_CANCEL,
            cls.REQUEST_DELETE,
            # Approval
            cls.REQUEST_APPROVE,
            cls.REQUEST_REJECT,
            # Allocation
            cls.ALLOCATION_CREATE,
            cls.ALLOCATION_VIEW,
            cls.ALLOCATION_MODIFY,
            cls.ALLOCATION_DELETE,
            # Trip execution
            cls.TRIP_CONFIRM,
            cls.TRIP_UPDATE_STATUS,
            cls.TRIP_COMPLETE,
            cls.TRIP_LOG,
            # Master data
            cls.VEHICLE_MANAGE,
            cls.DRIVER_MANAGE,
            cls.MAINTENANCE_MANAGE,
            # Dashboard
            cls.DASHBOARD_VIEW,
            cls.DASHBOARD_MANAGE,
            # Audit
            cls.AUDIT_VIEW,
        ]


class FleetUserRole:
    """
    Defines user role groups and their associated permissions.
    """
    
    DRIVER = "Driver"
    TRANSPORT_OFFICER = "Transport Officer"
    
    @staticmethod
    def get_driver_permissions():
        """Permissions for Driver role."""
        return [
            FleetPermission.REQUEST_VIEW_OWN,
            FleetPermission.TRIP_CONFIRM,
            FleetPermission.TRIP_UPDATE_STATUS,
            FleetPermission.TRIP_COMPLETE,
            FleetPermission.TRIP_LOG,
            FleetPermission.DASHBOARD_VIEW,
        ]
    
    @staticmethod
    def get_transport_officer_permissions():
        """Permissions for Transport Officer role."""
        return [
            FleetPermission.REQUEST_CREATE,
            FleetPermission.REQUEST_VIEW_ALL,
            FleetPermission.REQUEST_APPROVE,
            FleetPermission.REQUEST_REJECT,
            FleetPermission.ALLOCATION_CREATE,
            FleetPermission.ALLOCATION_VIEW,
            FleetPermission.ALLOCATION_MODIFY,
            FleetPermission.ALLOCATION_DELETE,
            FleetPermission.VEHICLE_MANAGE,
            FleetPermission.DRIVER_MANAGE,
            FleetPermission.MAINTENANCE_MANAGE,
            FleetPermission.DASHBOARD_VIEW,
            FleetPermission.DASHBOARD_MANAGE,
            FleetPermission.AUDIT_VIEW,
        ]
    
    @staticmethod
    def get_all_roles():
        """Return list of all role names."""
        return [FleetUserRole.DRIVER, FleetUserRole.TRANSPORT_OFFICER]


