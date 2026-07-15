from django.urls import path

from . import views

app_name = 'fleet'

urlpatterns = [
    path('vehicles/', views.VehicleListView.as_view(), name='vehicle_list'),
    path('vehicles/add/', views.VehicleCreateView.as_view(), name='vehicle_add'),
    path('vehicles/<int:pk>/', views.VehicleDetailView.as_view(), name='vehicle_detail'),
    path('vehicles/<int:pk>/edit/', views.VehicleEditView.as_view(), name='vehicle_edit'),
    path('vehicles/<int:pk>/fuel/add/', views.fuel_record_add, name='fuel_record_add'),
    path('vehicles/<int:pk>/fuel/export/', views.fuel_records_export, name='fuel_records_export'),
    path('vehicles/<int:pk>/maintenance/add/', views.maintenance_record_add, name='maintenance_record_add'),
    path('vehicles/<int:pk>/maintenance/export/', views.maintenance_records_export, name='maintenance_records_export'),
    path('drivers/', views.DriverListView.as_view(), name='driver_list'),
    path('drivers/add/', views.DriverCreateView.as_view(), name='driver_add'),
    path('drivers/<int:pk>/edit/', views.DriverEditView.as_view(), name='driver_edit'),
]
