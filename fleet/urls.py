"""
Fleet Management URL Routing
"""

from django.urls import path
from . import views

app_name = "fleet"

urlpatterns = [
    # Dashboard
    path('', views.FleetDashboardView.as_view(), name='dashboard'),

    # Transport Requests
    path('requests/', views.TransportRequestListView.as_view(), name='request_list'),
    path('requests/create/', views.TransportRequestCreateView.as_view(), name='request_create'),
    path('requests/<int:pk>/', views.TransportRequestDetailView.as_view(), name='request_detail'),
    path('requests/<int:pk>/edit/', views.TransportRequestUpdateView.as_view(), name='request_edit'),
    path('requests/<int:pk>/submit/', views.submit_request, name='request_submit'),
    path('requests/<int:pk>/approve/', views.approve_request, name='request_approve'),

    # Trip Allocation
    path('requests/<int:pk>/allocate/', views.allocate_trip, name='allocate_trip'),
    path('allocations/<uuid:pk>/confirm/', views.confirm_allocation, name='confirm_allocation'),
    path('allocations/<uuid:pk>/start/', views.start_trip, name='start_trip'),
    path('allocations/<uuid:pk>/complete/', views.complete_trip, name='complete_trip'),
    path('allocations/<uuid:pk>/cancel/', views.cancel_trip, name='cancel_trip'),
]
