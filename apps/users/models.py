from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import get_language
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _


class UserRole(models.TextChoices):
    """
    Built-in role codes. ADMIN is fixed; the trades below are only the ones the
    system ships with. Administrators add more worker types (``WorkerRole``) in the
    app, so code must never assume this list is complete — use the helpers below.
    """

    ADMIN = "ADMIN", "Administrator"
    ARRACHI = "ARRACHI", "Arrachi (Sawyer)"
    KRASKACHI = "KRASKACHI", "Kraskachi (Painter)"
    SHKURKACHI = "SHKURKACHI", "Shkurkachi (Sander)"
    ROVERCHI = "ROVERCHI", "Roverchi (CNC Operator)"
    SBORKACHI = "SBORKACHI", "Sborkachi (Assembler)"


ADMIN_ROLE = UserRole.ADMIN.value

code_validator = RegexValidator(
    r"^[A-Z][A-Z0-9_]{1,39}$",
    _("Kod lotin bosh harflari, raqamlar va _ dan iborat bo'lsin (masalan, PARDOZCHI)."),
)


class LocalizedName(models.Model):
    """A display name in the three interface languages; Uzbek is required."""

    name_uz = models.CharField(_("Nomi (o'zbekcha)"), max_length=100)
    name_en = models.CharField(_("Nomi (inglizcha)"), max_length=100, blank=True)
    name_ru = models.CharField(_("Nomi (ruscha)"), max_length=100, blank=True)

    class Meta:
        abstract = True

    @property
    def name(self) -> str:
        return localized(self.name_uz, self.name_en, self.name_ru)


def localized(name_uz: str, name_en: str = "", name_ru: str = "") -> str:
    """Pick the name for the active language, falling back to Uzbek."""
    lang = (get_language() or "uz")[:2]
    return {"en": name_en, "ru": name_ru}.get(lang) or name_uz


class WorkerRole(LocalizedName):
    """A trade (worker type). Materials are made visible to trades; workers pick theirs."""

    code = models.CharField(_("Kod"), max_length=40, unique=True, validators=[code_validator])
    is_active = models.BooleanField(
        _("Faol"),
        default=True,
        help_text=_("O'chirilsa, ro'yxatdan o'tishda tanlab bo'lmaydi; mavjud ishchilar kasbini saqlaydi."),
    )
    sort_order = models.PositiveIntegerField(_("Tartib"), default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name_uz"]
        verbose_name = _("kasb")
        verbose_name_plural = _("kasblar")

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Role lookups. Labels are cached per process and cleared on every request
# (LabelCacheMiddleware) and whenever a WorkerRole is saved, so pages never
# query once per row. Validation and ordering always read the database.
# ---------------------------------------------------------------------------
_role_label_cache: dict[str, tuple[str, str, str]] | None = None


def clear_role_cache() -> None:
    global _role_label_cache
    _role_label_cache = None


def _role_names() -> dict[str, tuple[str, str, str]]:
    global _role_label_cache
    if _role_label_cache is None:
        _role_label_cache = {
            code: (uz, en, ru)
            for code, uz, en, ru in WorkerRole.objects.values_list("code", "name_uz", "name_en", "name_ru")
        }
    return _role_label_cache


def role_label(code: str) -> str:
    if code == ADMIN_ROLE:
        return gettext("Administrator")
    names = _role_names().get(code)
    return localized(*names) if names else code


def worker_role_codes() -> list[str]:
    """Every known trade code (active or not), in display order."""
    return list(WorkerRole.objects.values_list("code", flat=True))


def worker_role_choices(include=()) -> list[tuple[str, str]]:
    """Active trades as form choices, plus any codes in ``include`` (e.g. already assigned)."""
    keep = set(include or ())
    return [
        (role.code, role.name)
        for role in WorkerRole.objects.all()
        if role.is_active or role.code in keep
    ]


def all_role_choices(include=()) -> list[tuple[str, str]]:
    return [(ADMIN_ROLE, gettext("Administrator")), *worker_role_choices(include)]


def normalize_roles(roles) -> list[str]:
    """De-duplicate roles, drop unknown codes, order as ADMIN first then trade order."""
    wanted = set(roles or [])
    if not wanted:
        return []
    order = [ADMIN_ROLE, *worker_role_codes()]
    return [role for role in order if role in wanted]


def validate_role_list(value) -> None:
    if not isinstance(value, list):
        raise ValidationError(_("Rollar ro'yxat (list) ko'rinishida bo'lishi kerak."))
    known = {ADMIN_ROLE, *worker_role_codes()}
    unknown = [role for role in value if role not in known]
    if unknown:
        raise ValidationError(_("Noma'lum rol(lar): %(roles)s"), params={"roles": ", ".join(map(str, unknown))})


def validate_worker_role_list(value) -> None:
    if not isinstance(value, list):
        raise ValidationError(_("Ruxsat etilgan kasblar ro'yxat (list) bo'lishi kerak."))
    known = set(worker_role_codes())
    unknown = [role for role in value if role not in known]
    if unknown:
        raise ValidationError(_("Noma'lum kasb(lar): %(roles)s"), params={"roles": ", ".join(map(str, unknown))})


class UserQuerySet(models.QuerySet):
    def pending_approval(self):
        return self.filter(is_approved=False, is_superuser=False, is_active=True)

    def approved(self):
        return self.filter(models.Q(is_approved=True) | models.Q(is_superuser=True))


class UserManager(DjangoUserManager.from_queryset(UserQuerySet)):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_approved", True)
        extra_fields.setdefault("roles", [ADMIN_ROLE])
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
        return self.is_superuser or role_name in self.roles or ADMIN_ROLE in self.roles

    @property
    def is_warehouse_admin(self) -> bool:
        return self.is_superuser or ADMIN_ROLE in (self.roles or [])

    @property
    def worker_roles(self) -> list[str]:
        return [role for role in (self.roles or []) if role != ADMIN_ROLE]

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
