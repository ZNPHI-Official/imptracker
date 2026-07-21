from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.generic import View

from accounts.mixins import GroupRequiredMixin

from .forms import SettingsForm
from .models import Settings


class SettingsView(GroupRequiredMixin, View):
    group_required = ['Fleet Manager', 'Superadmin']
    template_name = 'settings_app/settings.html'

    def get(self, request):
        form = SettingsForm(instance=Settings.load())
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = SettingsForm(request.POST, instance=Settings.load())
        if form.is_valid():
            form.save()
            messages.success(request, 'Settings saved.')
            return redirect('settings_app:settings')
        return render(request, self.template_name, {'form': form})
