from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext, pgettext_lazy


class UserRole(models.TextChoices):
    ADMIN = "ADMIN", _("Administrator")
    ARRACHI = "ARRACHI", pgettext_lazy("trade", "Arrachi")
    KRASKACHI = "KRASKACHI", pgettext_lazy("trade", "Kraskachi")
    SHKURKACHI = "SHKURKACHI", pgettext_lazy("trade", "Shkurkachi")
    ROVERCHI = "ROVERCHI", pgettext_lazy("trade", "Roverchi")
    SBORKACHI = "SBORKACHI", pgettext_lazy("trade", "Sborkachi")


class WorkerRole(models.Model):
    """A trade (kasb) workers register with. ADMIN is not a trade; it stays in UserRole.

    The five original trades are seeded by migration with the same codes as UserRole,
    so existing ``User.roles`` and ``BaseMaterial.allowed_roles`` values keep working.
    """

    code = models.CharField(_("Kod"), max_length=40, unique=True)
    name = models.CharField(_("Nomi"), max_length=100)
    sort_order = models.PositiveIntegerField(_("Tartib"), default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = _("kasb")
        verbose_name_plural = _("kasblar")

    def __str__(self) -> str:
        return self.name


# Trade codes and names are read on almost every page, so they are cached per process.
# The cache is cleared at the start of each request (RoleCacheMiddleware) and whenever a
# WorkerRole is saved, so a trade added in one worker process shows up everywhere.
_role_cache: list[tuple[str, str]] | None = None


def clear_role_cache(*args, **kwargs) -> None:
    global _role_cache
    _role_cache = None


def localized_trade_name(name: str) -> str:
    """The five built-in trade names are translated; trades admins added are shown as typed."""
    return pgettext("trade", name) if name else name


def worker_role_choices() -> list[tuple[str, str]]:
    """Trades as (code, name) pairs in display order and the current language. Usable as form ``choices``."""
    global _role_cache
    if _role_cache is None:
        _role_cache = list(WorkerRole.objects.values_list("code", "name"))
    return [(code, localized_trade_name(name)) for code, name in _role_cache]


def worker_role_codes() -> list[str]:
    return [code for code, _ in worker_role_choices()]


def all_role_choices() -> list[tuple[str, str]]:
    return [(UserRole.ADMIN.value, str(UserRole.ADMIN.label)), *worker_role_choices()]


def role_label(code: str) -> str:
    if code == UserRole.ADMIN:
        return str(UserRole.ADMIN.label)
    return dict(worker_role_choices()).get(code, code)


def normalize_roles(roles) -> list[str]:
    """De-duplicate roles; ADMIN first, then trades in display order. Unknown codes are dropped."""
    wanted = set(roles or [])
    return [role for role in [UserRole.ADMIN.value, *worker_role_codes()] if role in wanted]


def validate_role_list(value) -> None:
    if not isinstance(value, list):
        raise ValidationError(_("Rollar ro'yxat (list) ko'rinishida bo'lishi kerak."))
    known = {UserRole.ADMIN.value, *worker_role_codes()}
    unknown = [role for role in value if role not in known]
    if unknown:
        raise ValidationError(_("Noma'lum rol(lar): %(roles)s"), params={"roles": ", ".join(map(str, unknown))})


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
    full_name = models.CharField(_("To'liq ism"), max_length=255, blank=True)
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
        verbose_name = _("foydalanuvchi")
        verbose_name_plural = _("foydalanuvchilar")

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
        trades = set(worker_role_codes())
        return [role for role in (self.roles or []) if role in trades]

    @property
    def can_use_system(self) -> bool:
        """Active and approved (superusers never need approval)."""
        return self.is_active and (self.is_approved or self.is_superuser)

    @property
    def role_labels(self) -> list[str]:
        return [role_label(role) for role in (self.roles or [])]

    @property
    def display_name(self) -> str:
        return self.full_name or self.username
