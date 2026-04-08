
from django.db import models


class Funder(models.Model):
    code=models.CharField(max_length=20,unique=True)
    name=models.CharField(max_length=255)
    active=models.BooleanField(default=True)
    def __str__(self): return self.name

class ActivityStatus(models.Model):
    name=models.CharField(max_length=100)
    is_default=models.BooleanField(default=False)
    def __str__(self): return self.name


class Currency(models.Model):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=8, blank=True)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProcurementType(models.Model):
    code = models.CharField(max_length=20, unique=True, help_text="Short code for the procurement type")
    name = models.CharField(max_length=100, help_text="Display name for the procurement type")
    active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class ActivityCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Activity categories'

    def __str__(self):
        return self.name


class ActivitySubCategory(models.Model):
    category = models.ForeignKey(
        ActivityCategory,
        on_delete=models.CASCADE,
        related_name='sub_categories',
    )
    name = models.CharField(max_length=120)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category__name', 'name']
        unique_together = [('category', 'name')]
        verbose_name_plural = 'Activity sub categories'

    def __str__(self):
        return f"{self.category.name} - {self.name}"
