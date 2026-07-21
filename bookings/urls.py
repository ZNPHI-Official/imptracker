from django.urls import path

from . import views

app_name = 'bookings'

urlpatterns = [
    path('queue/', views.RequestQueueView.as_view(), name='request_queue'),
    path('my-requests/', views.MyRequestsView.as_view(), name='my_requests'),
    path('new/', views.TransportRequestCreateView.as_view(), name='request_create'),
    path('nudge/', views.CoordinationNudgeView.as_view(), name='coordination_nudge'),
    path('<int:pk>/', views.TransportRequestDetailView.as_view(), name='request_detail'),
    path('<int:pk>/cancel/', views.TransportRequestCancelView.as_view(), name='request_cancel'),
    path('<int:pk>/review/', views.RequestReviewView.as_view(), name='request_review'),
    path('htmx/districts/', views.DistrictOptionsView.as_view(), name='district_options'),
]
