from django.contrib import admin
from .models import Funder, ActivityStatus, Currency, ProcurementType, ProcurementStatus


@admin.register(Funder)
class FunderAdmin(admin.ModelAdmin):
	list_display = ('code', 'name', 'active')


@admin.register(ActivityStatus)
class ActivityStatusAdmin(admin.ModelAdmin):
	list_display = ('name', 'is_default')


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
	list_display = ('code', 'name', 'symbol', 'is_default')


@admin.register(ProcurementType)
class ProcurementTypeAdmin(admin.ModelAdmin):
	list_display = ('code', 'name', 'active', 'is_default')
	list_filter = ('active', 'is_default')
	search_fields = ('code', 'name')

@admin.register(ProcurementStatus)
class ProcurementStatusAdmin(admin.ModelAdmin):
	list_display = ('name', 'is_default')
