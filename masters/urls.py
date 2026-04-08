from django.urls import path
from . import views

app_name = 'masters'

urlpatterns = [
    # Funder Management
    path('funders/', views.funder_list, name='funder_list'),
    path('funders/create/', views.funder_create, name='funder_create'),
    path('funders/<int:pk>/edit/', views.funder_edit, name='funder_edit'),
    path('funders/<int:pk>/delete/', views.funder_delete, name='funder_delete'),
    
    # Status Management
    path('statuses/', views.status_list, name='status_list'),
    path('statuses/create/', views.status_create, name='status_create'),
    path('statuses/<int:pk>/edit/', views.status_edit, name='status_edit'),
    path('statuses/<int:pk>/delete/', views.status_delete, name='status_delete'),
    
    # Currency Management
    path('currencies/', views.currency_list, name='currency_list'),
    path('currencies/create/', views.currency_create, name='currency_create'),
    path('currencies/<int:pk>/edit/', views.currency_edit, name='currency_edit'),
    path('currencies/<int:pk>/delete/', views.currency_delete, name='currency_delete'),
    
    # Cluster Management
    path('clusters/', views.cluster_list, name='cluster_list'),
    path('clusters/create/', views.cluster_create, name='cluster_create'),
    path('clusters/<int:pk>/edit/', views.cluster_edit, name='cluster_edit'),
    path('clusters/<int:pk>/delete/', views.cluster_delete, name='cluster_delete'),
    
    # Procurement Type Management
    path('procurement-types/', views.procurement_type_list, name='procurement_type_list'),
    path('procurement-types/create/', views.procurement_type_create, name='procurement_type_create'),
    path('procurement-types/<int:pk>/edit/', views.procurement_type_edit, name='procurement_type_edit'),
    path('procurement-types/<int:pk>/delete/', views.procurement_type_delete, name='procurement_type_delete'),

    # Activity Category Management
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('sub-categories/create/', views.sub_category_create, name='sub_category_create'),
    path('sub-categories/<int:pk>/move/', views.sub_category_move, name='sub_category_move'),
    path('categories/<int:pk>/convert-to-sub-category/', views.category_convert_to_sub_category, name='category_convert_to_sub_category'),
]
