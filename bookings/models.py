from django.conf import settings
from django.db import models


class Province(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class District(models.Model):
    name = models.CharField(max_length=100)
    province = models.ForeignKey(Province, on_delete=models.CASCADE, related_name='districts')

    class Meta:
        ordering = ['name']
        unique_together = [['name', 'province']]

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TransportRequest(models.Model):
    STATUS_CHOICES = [
        ('Submitted', 'Submitted'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
        ('Cancelled', 'Cancelled'),
    ]

    requester_name = models.CharField(max_length=200)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='transport_requests')
    position = models.CharField(max_length=200)
    programme_activity = models.CharField(max_length=300)
    date_of_request = models.DateField(auto_now_add=True)
    period_from = models.DateField()
    period_to = models.DateField()
    province = models.ForeignKey(Province, on_delete=models.PROTECT, related_name='transport_requests')
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name='transport_requests')
    destination = models.CharField(max_length=300)
    num_vehicles = models.PositiveIntegerField(default=1)
    num_drivers = models.PositiveIntegerField(default=1)
    num_passengers = models.PositiveIntegerField(default=1)
    is_emergency = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Submitted')
    admin_comment = models.TextField(blank=True)
    # Set to True once the requester has acknowledged the coordination nudge.
    coordination_acknowledged = models.BooleanField(default=False)
    # Optional note from the requester explaining why they still need a separate vehicle.
    coordination_note = models.TextField(blank=True)
    approved_date = models.DateField(null=True, blank=True)
    # The user account that submitted this request (not necessarily the traveller).
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_requests',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.requester_name} — {self.programme_activity} ({self.status})"

    @property
    def is_late_booking(self):
        """True if submitted less than 2 weeks before the assignment start date."""
        from datetime import date, timedelta
        return self.period_from - date.today() < timedelta(weeks=2)


class TripAssignment(models.Model):
    """Links one TransportRequest to one Vehicle and one Driver.

    A request requiring 3 vehicles produces 3 TripAssignment rows, all pointing
    to the same TransportRequest.
    """
    transport_request = models.ForeignKey(
        TransportRequest, on_delete=models.CASCADE, related_name='assignments'
    )
    vehicle = models.ForeignKey(
        'fleet.Vehicle', on_delete=models.PROTECT, related_name='assignments'
    )
    driver = models.ForeignKey(
        'fleet.Driver', on_delete=models.PROTECT, related_name='assignments'
    )

    def __str__(self):
        return f"{self.vehicle} + {self.driver} → {self.transport_request}"
