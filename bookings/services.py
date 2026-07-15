"""Cross-model business logic for the bookings app.

Keeps the operational status of vehicles and drivers (`On Trip` / `On Assignment`
vs `Available`) in sync with the trips they are currently serving. The trip
lifecycle is the source of truth; manually-managed states are left untouched.
"""
from fleet.models import Driver, Vehicle
from .models import TripAssignment

# A vehicle/driver counts as actively committed only while its trip is In Progress.
ACTIVE_TRIP_STATUS = 'In Progress'

# Manually-managed states the trip lifecycle must never overwrite. A vehicle a
# manager parked in the workshop (or holds as an emergency reserve), or a driver
# on leave, stays that way even if somehow linked to an active trip.
VEHICLE_MANUAL_STATUSES = ('In Maintenance', 'Emergency Standby')
DRIVER_MANUAL_STATUSES = ('On Leave',)


def sync_fleet_statuses():
    """Reconcile every vehicle's and driver's status with current in-progress trips.

    Idempotent and drift-proof: it sets `On Trip` / `On Assignment` for anything
    serving an in-progress trip, and reverts anything previously marked so once its
    trip is no longer active. Reverts only touch the trip-managed states, so manual
    statuses (In Maintenance, Emergency Standby, On Leave) are preserved.
    """
    active = TripAssignment.objects.filter(transport_request__status=ACTIVE_TRIP_STATUS)
    on_trip_vehicle_ids = set(active.values_list('vehicle_id', flat=True))
    on_assignment_driver_ids = set(active.values_list('driver_id', flat=True))

    # Promote vehicles/drivers now on an active trip (unless manually held).
    Vehicle.objects.filter(id__in=on_trip_vehicle_ids) \
        .exclude(status__in=VEHICLE_MANUAL_STATUSES) \
        .exclude(status='On Trip') \
        .update(status='On Trip')
    Driver.objects.filter(id__in=on_assignment_driver_ids) \
        .exclude(status__in=DRIVER_MANUAL_STATUSES) \
        .exclude(status='On Assignment') \
        .update(status='On Assignment')

    # Release anything still flagged as committed whose trip has ended/changed.
    Vehicle.objects.filter(status='On Trip') \
        .exclude(id__in=on_trip_vehicle_ids) \
        .update(status='Available')
    Driver.objects.filter(status='On Assignment') \
        .exclude(id__in=on_assignment_driver_ids) \
        .update(status='Available')
