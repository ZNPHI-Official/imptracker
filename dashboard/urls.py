from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('gantt/', views.GanttView.as_view(), name='gantt'),
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('district-data/', views.DistrictDataView.as_view(), name='district_data'),
]
