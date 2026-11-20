from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import User, normalize_roles


@transaction.atomic
def register_worker(*, username: str, password: str, full_name: str, roles: list[str]) -> User:
    """Create a self-registered worker. Access stays locked until an admin approves."""
    roles = normalize_roles(roles)
    if not roles:
        raise ValidationError({"roles": "Kamida bitta kasbni tanlang."})
    user = User(username=username, full_name=full_name, roles=roles, is_approved=False, is_active=True)
    user.set_password(password)
    user.full_clean()
    user.save()
    return user


@transaction.atomic
def approve_user(user: User, *, approved_by: User, roles: list[str] | None = None) -> User:
    if roles is not None:
        user.roles = normalize_roles(roles)
    if not user.roles:
        raise ValidationError({"roles": "Tasdiqlashdan oldin kamida bitta rol belgilang."})
    user.is_approved = True
    user.is_active = True
    user.approved_at = timezone.now()
    user.approved_by = approved_by
    user.save()
    return user


@transaction.atomic
def reject_registration(user: User) -> None:
    """Discard a pending registration request (pending accounts have no ledger history)."""
    if user.is_approved or user.is_superuser:
        raise ValidationError("Faqat tasdiqlanmagan so'rovlarni rad etish mumkin.")
    user.delete()
