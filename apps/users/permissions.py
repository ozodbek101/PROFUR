"""Role-based access control for both the HTML views and the DRF API."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from rest_framework.permissions import BasePermission


def is_approved_user(user) -> bool:
    return bool(user and user.is_authenticated and user.can_use_system)


def is_warehouse_admin(user) -> bool:
    return is_approved_user(user) and user.is_warehouse_admin


# --- Django class-based view mixins -----------------------------------------
class ApprovedUserRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Any approved worker or admin."""

    def test_func(self) -> bool:
        return is_approved_user(self.request.user)


class WarehouseAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Administrators only (ADMIN role or superuser)."""

    def test_func(self) -> bool:
        return is_warehouse_admin(self.request.user)


# --- DRF permission classes ----------------------------------------------------
class IsApprovedUser(BasePermission):
    message = "Hisobingiz administrator tomonidan tasdiqlanmagan."

    def has_permission(self, request, view) -> bool:
        return is_approved_user(request.user)


class IsWarehouseAdmin(BasePermission):
    message = "Bu amal faqat administratorlar uchun."

    def has_permission(self, request, view) -> bool:
        return is_warehouse_admin(request.user)
