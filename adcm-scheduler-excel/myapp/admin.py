from django.contrib import admin as dj_admin

from .models import ActiveLink, Task2, Link


class WorkAdmin(dj_admin.ModelAdmin):
    list_display = ("id", "name")


dj_admin.site.register(ActiveLink)
dj_admin.site.register(Task2)
dj_admin.site.register(Link)