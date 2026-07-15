
from django.contrib.auth.models import AbstractUser
from django.db import models

class Cluster(models.Model):
    short_name=models.CharField(max_length=20,unique=True)
    full_name=models.CharField(max_length=255)
    def __str__(self): return self.short_name

class User(AbstractUser):
    clusters=models.ManyToManyField(Cluster,blank=True)
    coordinated_funder=models.ForeignKey('masters.Funder', null=True, blank=True, on_delete=models.SET_NULL, help_text="Funder that this Project Coordinator manages")
    position=models.CharField(max_length=200, blank=True, help_text="Job title, used to prefill transport requests")
    
    def roles(self):
        """Return a list of role names (Django Groups) for the user."""
        return [g.name for g in self.groups.all()]

    def has_role(self, role_name):
        return self.groups.filter(name=role_name).exists()
