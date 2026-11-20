from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.db import models


class UserRole(models.TextChoices):
    ADMIN = "ADMIN", "Administrator"
    ARRACHI = "ARRACHI", "Arrachi (Sawyer)"
    KRASKACHI = "KRASKACHI", "Kraskachi (Painter)"
    SHKURKACHI = "SHKURKACHI", "Shkurkachi (Sander)"
    ROVERCHI = "ROVERCHI", "Roverchi (CNC Operator)"
    SBORKACHI = "SBORKACHI", "Sborkachi (Assembler)"


#: Roles a worker may pick on the self-registration form (ADMIN is assigned by admins only).
WORKER_ROLES: tuple[str, ...] = tuple(role for role in UserRole.values if role != UserRole.ADMIN)
WORKER_ROLE_CHOICES = [(role.value, role.label) for role in UserRole if role != UserRole.ADMIN]


def normalize_roles(roles) -> list[str]:
    """De-duplicate roles and keep them in canonical UserRole order."""
    wanted = set(roles or [])
    return [role for role in UserRole.values if role in wanted]


def validate_role_list(value) -> None:
    if not isinstance(value, list):
        raise ValidationError("Rollar ro'yxat (list) ko'rinishida bo'lishi kerak.")
    unknown = [role for role in value if role not in UserRole.values]
    if unknown:
        raise ValidationError("Noma'lum rol(lar): %(roles)s", params={"roles": ", ".join(map(str, unknown))})


class UserQuerySet(models.QuerySet):
    def pending_approval(self):
        return self.filter(is_approved=False, is_superuser=False, is_active=True)

    def approved(self):
        return self.filter(models.Q(is_approved=True) | models.Q(is_superuser=True))


class UserManager(DjangoUserManager.from_queryset(UserQuerySet)):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_approved", True)
        extra_fields.setdefault("roles", [UserRole.ADMIN.value])
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    full_name = models.CharField("To'liq ism", max_length=255, blank=True)
    roles = models.JSONField(
        default=list,
        blank=True,
        validators=[validate_role_list],
        help_text="List of assigned UserRole strings",
    )
    is_approved = models.BooleanField(
        default=False, help_text="Admin approval status for worker login"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    objects = UserManager()

    class Meta:
        ordering = ["full_name", "username"]
        verbose_name = "foydalanuvchi"
        verbose_name_plural = "foydalanuvchilar"

    def __str__(self) -> str:
        return self.full_name or self.username

    def save(self, *args, **kwargs):
        self.roles = normalize_roles(self.roles)
        super().save(*args, **kwargs)

    # --- Role helpers -----------------------------------------------------
    def has_role(self, role_name: str) -> bool:
        return self.is_superuser or role_name in self.roles or UserRole.ADMIN in self.roles

    @property
    def is_warehouse_admin(self) -> bool:
        return self.is_superuser or UserRole.ADMIN in (self.roles or [])

    @property
    def worker_roles(self) -> list[str]:
        return [role for role in (self.roles or []) if role in WORKER_ROLES]

    @property
    def can_use_system(self) -> bool:
        """Active and approved (superusers never need approval)."""
        return self.is_active and (self.is_approved or self.is_superuser)

    @property
    def role_labels(self) -> list[str]:
        return [UserRole(role).label for role in (self.roles or []) if role in UserRole.values]

    @property
    def display_name(self) -> str:
        return self.full_name or self.username
