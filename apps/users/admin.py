from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User, WorkerRole


@admin.register(WorkerRole)
class WorkerRoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name_uz", "name_en", "name_ru", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    readonly_fields = ("code",)

    def has_delete_permission(self, request, obj=None):
        return False  # users and materials refer to trades by code; deactivate instead


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "full_name", "roles", "is_approved", "is_active", "date_joined")
    list_filter = ("is_approved", "is_active", "is_superuser")
    search_fields = ("username", "full_name")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Ombor (WMS)", {"fields": ("full_name", "roles", "is_approved", "approved_at", "approved_by")}),
    )
    readonly_fields = ("approved_at", "approved_by")
