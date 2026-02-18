from django.urls import path
from . import views

app_name = 'dashboards'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('my-space/', views.my_space, name='my_space'),
    path('save/', views.save_dashboard, name='save_dashboard'),
    path('load/<int:view_id>/', views.load_dashboard, name='load_dashboard'),
    path('list/', views.list_saved_dashboards, name='list_saved_dashboards'),
    path('delete/<int:view_id>/', views.delete_saved_dashboard, name='delete_saved_dashboard'),
]
