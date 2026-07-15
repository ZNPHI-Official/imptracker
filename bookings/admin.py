from django.contrib import admin
from .models import Province, District, Department, TransportRequest, TripAssignment


@admin.register(Province)
class ProvinceAdmin(admin.ModelAdmin):
    list_display = ['name', 'district_count']
    search_fields = ['name']

    @admin.display(description='Districts')
    def district_count(self, obj):
        return obj.districts.count()


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ['name', 'province']
    list_filter = ['province']
    search_fields = ['name']


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


class TripAssignmentInline(admin.TabularInline):
    model = TripAssignment
    extra = 1
    autocomplete_fields = ['vehicle', 'driver']


@admin.register(TransportRequest)
class TransportRequestAdmin(admin.ModelAdmin):
    list_display = [
        'requester_name', 'department', 'period_from', 'period_to',
        'district', 'status', 'is_emergency', 'date_of_request',
    ]
    list_filter = ['status', 'is_emergency', 'department', 'province']
    search_fields = ['requester_name', 'programme_activity', 'destination']
    date_hierarchy = 'date_of_request'
    readonly_fields = ['date_of_request', 'created_at', 'updated_at']
    inlines = [TripAssignmentInline]


@admin.register(TripAssignment)
class TripAssignmentAdmin(admin.ModelAdmin):
    list_display = ['transport_request', 'vehicle', 'driver']
    list_filter = ['vehicle', 'driver']
    search_fields = ['transport_request__requester_name', 'vehicle__license_plate', 'driver__name']
