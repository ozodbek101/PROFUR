from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "full_name", "roles", "is_approved", "is_active", "date_joined")
    list_filter = ("is_approved", "is_active", "is_superuser")
    search_fields = ("username", "full_name")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (_("Ombor (WMS)"), {"fields": ("full_name", "roles", "is_approved", "approved_at", "approved_by")}),
    )
    readonly_fields = ("approved_at", "approved_by")
