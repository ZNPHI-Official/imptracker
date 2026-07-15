from django.urls import path

from .views import SettingsView

app_name = 'settings_app'

urlpatterns = [
    path('', SettingsView.as_view(), name='settings'),
]
