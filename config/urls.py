from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.views import LogoutView
from django.views.generic import RedirectView
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.contrib.auth import logout
from uploads import views as upload_views
from dashboards import views as dashboard_views
from django.contrib.auth import views as auth_views
from activities import views as activities_views
from ui import views as ui_views

# Custom logout that handles GET requests and properly destroys session
def logout_view(request):
    logout(request)
    return HttpResponseRedirect('/login/')

# Root view - redirect authenticated users to dashboard, others to login
def root_view(request):
    if request.user.is_authenticated:
        return RedirectView.as_view(url='dashboard')(request)
    return auth_views.LoginView.as_view(template_name='registration/login.html')(request)

urlpatterns = [
	path('', root_view, name='home'),
    path('jet/', include('jet.urls', 'jet')),  # Django JET URLS
    path('jet/dashboard/', include('jet.dashboard.urls', 'jet-dashboard')),  # Django JET dashboard URLS
	path('omega/', admin.site.urls, name='omega_admin'),
	path('uploads/template/', upload_views.download_template, name='download_template'),
	path('uploads/upload/', upload_views.upload_activities, name='upload_activities'),
	path('dashboard/', include('dashboards.urls')),
	path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
	path('logout/', logout_view, name='logout'),
	path('activities/', activities_views.activities_list, name='activities_list'),
	path('activities/create/', activities_views.create_activity, name='create_activity'),
	path('activities/bulk-action/', activities_views.bulk_action, name='bulk_action'),
	path('activities/procurement/', activities_views.procurement_list, name='procurement_list'),
	path('activities/procurement/export/', activities_views.export_procurement_excel, name='export_procurement_excel'),
	path('activities/procurement/<int:pk>/', activities_views.procurement_detail, name='procurement_detail'),
	path('activities/<int:pk>/', activities_views.activity_detail, name='activity_detail'),
	path('activities/<int:pk>/edit/', activities_views.edit_activity, name='edit_activity'),
	path('activities/<int:pk>/delete/', activities_views.delete_activity, name='delete_activity'),
	path('activities/<int:pk>/update-field/', activities_views.update_activity_field, name='update_activity_field'),
	
	# Attachment endpoints
	path('activities/<int:pk>/attachments/upload/', activities_views.upload_attachment, name='upload_attachment'),
	path('activities/<int:pk>/attachments/', activities_views.list_attachments, name='list_attachments'),
	path('activities/<int:pk>/attachments/versions/', activities_views.get_attachment_versions, name='get_attachment_versions'),
	path('attachments/<int:pk>/delete/', activities_views.delete_attachment, name='delete_attachment'),
	path('attachments/<int:pk>/download/', activities_views.download_attachment, name='download_attachment'),

	# Settings (System Admin only)
	path('settings/', ui_views.settings, name='settings'),

	# Include app URLs
	path('accounts/', include('accounts.urls')),
	path('masters/', include('masters.urls')),
	path('fleet/', include('fleet.urls')),
]
