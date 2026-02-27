from django.urls import path

from . import views

app_name = 'support'

urlpatterns = [
    path('', views.support_list, name='list'),
    path('<int:pk>/status/', views.update_issue_status, name='update_status'),
    path('<int:pk>/delete/', views.delete_issue, name='delete_issue'),
]
