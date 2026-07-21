from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Vehicle(models.Model):
    VEHICLE_TYPE_CHOICES = [
        ('Hilux', 'Hilux'),
        ('Land Cruiser', 'Land Cruiser'),
    ]
    FUEL_TYPE_CHOICES = [
        ('Diesel', 'Diesel'),
        ('Petrol', 'Petrol'),
    ]
    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('On Trip', 'On Trip'),
        ('In Maintenance', 'In Maintenance'),
        ('Emergency Standby', 'Emergency Standby'),
    ]

    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.PositiveIntegerField()
    license_plate = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPE_CHOICES)
    current_mileage = models.PositiveIntegerField(help_text='Current odometer reading in km.')
    seating_capacity = models.PositiveIntegerField()
    fuel_type = models.CharField(max_length=10, choices=FUEL_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    # Per-vehicle maintenance interval — overrides the system default when set individually.
    maintenance_interval_km = models.PositiveIntegerField(default=5000)
    # Updated automatically when a new MaintenanceRecord is saved (via signal below).
    last_service_date = models.DateField(null=True, blank=True)
    last_service_mileage = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['license_plate']

    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.license_plate})"

    @property
    def km_until_service(self):
        """Kilometres remaining before next scheduled service. Negative means overdue."""
        if self.last_service_mileage is None:
            return None
        return (self.last_service_mileage + self.maintenance_interval_km) - self.current_mileage

    @property
    def maintenance_status(self):
        """Traffic-light status: 'green', 'amber', or 'red'."""
        km = self.km_until_service
        if km is None:
            return 'unknown'
        if km < 0:
            return 'red'
        if km <= 500:
            return 'amber'
        return 'green'


class Driver(models.Model):
    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('On Assignment', 'On Assignment'),
        ('On Leave', 'On Leave'),
    ]

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class FuelRecord(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='fuel_records')
    date = models.DateField()
    liters = models.DecimalField(max_digits=8, decimal_places=2)
    cost_per_liter = models.DecimalField(max_digits=8, decimal_places=2)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2)
    location = models.CharField(max_length=200)
    mileage_at_fillup = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"Fuel: {self.vehicle} on {self.date} ({self.liters}L)"


class MaintenanceRecord(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='maintenance_records')
    date = models.DateField()
    mileage_at_service = models.PositiveIntegerField()
    service_type = models.CharField(max_length=200)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    vendor = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"Maintenance: {self.vehicle} on {self.date} ({self.service_type})"


@receiver(post_save, sender=MaintenanceRecord)
def update_vehicle_service_baseline(sender, instance, **kwargs):
    """Keep Vehicle.last_service_date and last_service_mileage in sync with the most
    recent MaintenanceRecord. Using the latest by date (then mileage as tiebreaker)
    so that deleting or back-dating a record stays consistent."""
    latest = (
        MaintenanceRecord.objects
        .filter(vehicle=instance.vehicle)
        .order_by('-date', '-mileage_at_service')
        .first()
    )
    if latest:
        Vehicle.objects.filter(pk=instance.vehicle_id).update(
            last_service_date=latest.date,
            last_service_mileage=latest.mileage_at_service,
        )
