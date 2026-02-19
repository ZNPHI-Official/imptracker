"""
Fleet Allocation Engine

Optimized algorithms for vehicle and driver allocation.
Provides advanced filtering and performance improvements.
"""

from django.db import models
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone
from datetime import datetime, timedelta

from .models import (
    Vehicle, Driver, TransportRequest, TripAllocation,
    VehicleStatus, DriverStatus, TripAllocationStatus
)


class AllocationEngine:
    """
    Optimized allocation engine for finding available vehicles and drivers.
    """

    @staticmethod
    def get_available_vehicles(departure_dt, return_dt, vehicle_type=None, min_capacity=None):
        """
        Get available vehicles for the given time period with optional filters.

        Args:
            departure_dt: Departure datetime
            return_dt: Return datetime
            vehicle_type: Optional vehicle type filter
            min_capacity: Optional minimum passenger capacity

        Returns:
            QuerySet of available Vehicle objects
        """
        # Base query for available vehicles
        base_query = Q(
            status=VehicleStatus.AVAILABLE,
            is_active=True
        )

        # Add vehicle type filter
        if vehicle_type:
            base_query &= Q(vehicle_type=vehicle_type)

        # Add capacity filter (basic estimation based on vehicle type)
        if min_capacity:
            capacity_map = {
                'sedan': 4,
                'suv': 6,
                'van': 8,
                'minibus': 15,
                'truck': 2,
            }
            suitable_types = [
                vtype for vtype, capacity in capacity_map.items()
                if capacity >= min_capacity
            ]
            if suitable_types:
                base_query &= Q(vehicle_type__in=suitable_types)

        # Get vehicles that don't have conflicting allocations
        conflicting_allocations = TripAllocation.objects.filter(
            vehicle=OuterRef('pk'),
            status__in=[
                TripAllocationStatus.ALLOCATED,
                TripAllocationStatus.CONFIRMED,
                TripAllocationStatus.IN_PROGRESS
            ]
        ).filter(
            # Overlapping time periods
            Q(
                transport_request__departure_datetime__lt=return_dt,
                transport_request__return_datetime__gt=departure_dt
            )
        )

        return Vehicle.objects.filter(base_query).exclude(
            Exists(conflicting_allocations)
        ).select_related().order_by('registration_number')

    @staticmethod
    def get_available_drivers(departure_dt, return_dt, location=None):
        """
        Get available drivers for the given time period with optional filters.

        Args:
            departure_dt: Departure datetime
            return_dt: Return datetime
            location: Optional location filter

        Returns:
            QuerySet of available Driver objects
        """
        # Base query for available drivers
        base_query = Q(
            status=DriverStatus.AVAILABLE,
            is_active=True,
            license_expiry_date__gt=timezone.now().date()
        )

        # Add location filter
        if location:
            base_query &= Q(assigned_location__icontains=location)

        # Get drivers that don't have conflicting allocations
        conflicting_allocations = TripAllocation.objects.filter(
            driver=OuterRef('pk'),
            status__in=[
                TripAllocationStatus.ALLOCATED,
                TripAllocationStatus.CONFIRMED,
                TripAllocationStatus.IN_PROGRESS
            ]
        ).filter(
            # Overlapping time periods
            Q(
                transport_request__departure_datetime__lt=return_dt,
                transport_request__return_datetime__gt=departure_dt
            )
        )

        return Driver.objects.filter(base_query).exclude(
            Exists(conflicting_allocations)
        ).select_related('user').order_by('user__first_name', 'user__last_name')

    @staticmethod
    def find_best_allocation(departure_dt, return_dt, preferences=None):
        """
        Find the best vehicle-driver combination based on preferences.

        Args:
            departure_dt: Departure datetime
            return_dt: Return datetime
            preferences: Dict with preference criteria

        Returns:
            Dict with recommended vehicle and driver, or None
        """
        preferences = preferences or {}

        vehicle_type = preferences.get('vehicle_type')
        min_capacity = preferences.get('min_capacity')
        preferred_location = preferences.get('location')
        prioritize_fuel_efficiency = preferences.get('fuel_efficient', False)

        # Get available vehicles and drivers
        vehicles = AllocationEngine.get_available_vehicles(
            departure_dt, return_dt, vehicle_type, min_capacity
        )
        drivers = AllocationEngine.get_available_drivers(
            departure_dt, return_dt, preferred_location
        )

        if not vehicles or not drivers:
            return None

        # Simple matching algorithm - can be enhanced
        # For now, just return first available combination
        # Future: implement scoring based on distance, fuel efficiency, etc.

        vehicle = vehicles.first()
        driver = drivers.first()

        if vehicle and driver:
            return {
                'vehicle': vehicle,
                'driver': driver,
                'score': 1.0,  # Basic score
                'reason': 'First available combination'
            }

        return None

    @staticmethod
    def check_allocation_conflicts(vehicle, driver, departure_dt, return_dt):
        """
        Check if a specific vehicle-driver combination has conflicts.

        Args:
            vehicle: Vehicle instance
            driver: Driver instance
            departure_dt: Departure datetime
            return_dt: Return datetime

        Returns:
            Dict with conflict information
        """
        conflicts = {
            'vehicle_conflicts': [],
            'driver_conflicts': [],
            'has_conflicts': False
        }

        # Check vehicle conflicts
        vehicle_conflicts = TripAllocation.objects.filter(
            vehicle=vehicle,
            status__in=[
                TripAllocationStatus.ALLOCATED,
                TripAllocationStatus.CONFIRMED,
                TripAllocationStatus.IN_PROGRESS
            ]
        ).filter(
            Q(
                transport_request__departure_datetime__lt=return_dt,
                transport_request__return_datetime__gt=departure_dt
            )
        ).select_related('transport_request')

        if vehicle_conflicts.exists():
            conflicts['vehicle_conflicts'] = list(vehicle_conflicts)
            conflicts['has_conflicts'] = True

        # Check driver conflicts
        driver_conflicts = TripAllocation.objects.filter(
            driver=driver,
            status__in=[
                TripAllocationStatus.ALLOCATED,
                TripAllocationStatus.CONFIRMED,
                TripAllocationStatus.IN_PROGRESS
            ]
        ).filter(
            Q(
                transport_request__departure_datetime__lt=return_dt,
                transport_request__return_datetime__gt=departure_dt
            )
        ).select_related('transport_request')

        if driver_conflicts.exists():
            conflicts['driver_conflicts'] = list(driver_conflicts)
            conflicts['has_conflicts'] = True

        return conflicts


class AdvancedAllocationFilter:
    """
    Advanced filtering options for allocation queries.
    """

    VEHICLE_FILTERS = {
        'vehicle_type': 'Vehicle Type',
        'fuel_type': 'Fuel Type',
        'assigned_location': 'Location',
        'is_active': 'Active Status',
    }

    DRIVER_FILTERS = {
        'assigned_location': 'Location',
        'is_active': 'Active Status',
        'license_expiry_date': 'License Valid',
    }

    @staticmethod
    def get_vehicle_filters():
        """Get available vehicle filter options."""
        return {
            'vehicle_types': dict(Vehicle.VEHICLE_TYPES),
            'fuel_types': dict(Vehicle.FUEL_TYPES),
            'locations': list(Vehicle.objects.values_list(
                'assigned_location', flat=True
            ).distinct().exclude(assigned_location='')),
        }

    @staticmethod
    def get_driver_filters():
        """Get available driver filter options."""
        return {
            'locations': list(Driver.objects.values_list(
                'assigned_location', flat=True
            ).distinct().exclude(assigned_location='')),
        }