from django.contrib import admin
from .models import Vehicle, Driver, FuelRecord, MaintenanceRecord


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['license_plate', 'make', 'model', 'year', 'vehicle_type', 'status', 'current_mileage', 'maintenance_status']
    list_filter = ['status', 'vehicle_type', 'fuel_type']
    search_fields = ['license_plate', 'make', 'model']
    readonly_fields = ['created_at', 'updated_at', 'last_service_date', 'last_service_mileage']

    @admin.display(description='Maintenance')
    def maintenance_status(self, obj):
        return obj.maintenance_status


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ['name', 'phone', 'status']
    list_filter = ['status']
    search_fields = ['name']


@admin.register(FuelRecord)
class FuelRecordAdmin(admin.ModelAdmin):
    list_display = ['vehicle', 'date', 'liters', 'total_cost', 'location']
    list_filter = ['vehicle', 'date']
    search_fields = ['vehicle__license_plate', 'location']
    date_hierarchy = 'date'


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ['vehicle', 'date', 'service_type', 'mileage_at_service', 'cost', 'vendor']
    list_filter = ['vehicle', 'date']
    search_fields = ['vehicle__license_plate', 'service_type', 'vendor']
    date_hierarchy = 'date'
    readonly_fields = ['created_at']
