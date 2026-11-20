from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.users.models import (
    LocalizedName,
    code_validator,
    localized,
    normalize_roles,
    role_label,
    validate_worker_role_list,
)

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")


class MaterialCategory(models.TextChoices):
    """
    Built-in category codes the system ships with. Administrators add more
    categories (``Category``) in the app, so never treat this list as complete.
    """

    SHEET = "SHEET", "Sheet & Board Materials (MDF, Fanera, PVC, Shpon)"
    LIQUID = "LIQUID", "Liquids & Paints (Kraska, Lak, Gruntovka)"
    LINEAR = "LINEAR", "Linear Materials (Lenta, Shkurka roll)"
    HARDWARE = "HARDWARE", "Hardware & Fittings (Furnitura, Samarez, Handles, Legs)"


class MeasurementUnit(models.TextChoices):
    SHEET_COUNT = "SHEET", _("Dona (list)")
    LITER = "LITER", _("Litr (L)")
    KILOGRAM = "KG", _("Kilogramm (kg)")
    METER = "METER", _("Metr (m)")
    CENTIMETER = "CM", _("Santimetr (sm)")
    PIECE = "PIECE", _("Dona")


#: Short unit labels for compact tables and buttons.
UNIT_SHORT_LABELS = {
    MeasurementUnit.SHEET_COUNT: _("dona"),
    MeasurementUnit.LITER: "L",
    MeasurementUnit.KILOGRAM: "kg",
    MeasurementUnit.METER: "m",
    MeasurementUnit.CENTIMETER: _("sm"),
    MeasurementUnit.PIECE: _("dona"),
}

#: Units that can only move in whole numbers (you cannot take 1.5 hinges).
INTEGER_UNITS = frozenset({MeasurementUnit.SHEET_COUNT, MeasurementUnit.PIECE})


class Category(LocalizedName):
    """A material category, managed by administrators."""

    code = models.CharField(_("Kod"), max_length=40, unique=True, validators=[code_validator])
    default_roles = models.JSONField(
        _("Standart kasblar"),
        default=list,
        blank=True,
        validators=[validate_worker_role_list],
        help_text=_("Yangi material uchun kasb belgilanmasa, shu kasblar ko'radi va oladi."),
    )
    supports_offcuts = models.BooleanField(
        _("Qoldiq yoziladi"),
        default=False,
        help_text=_("List yoki lenta kabi kesiladigan materiallar uchun: qoldiq (uzunlik × eni) qayd etiladi."),
    )
    is_active = models.BooleanField(
        _("Faol"), default=True, help_text=_("O'chirilsa, yangi material uchun tanlab bo'lmaydi; mavjudlari qoladi.")
    )
    sort_order = models.PositiveIntegerField(_("Tartib"), default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name_uz"]
        verbose_name = _("kategoriya")
        verbose_name_plural = _("kategoriyalar")

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.default_roles = normalize_roles(self.default_roles)
        super().save(*args, **kwargs)

    @property
    def default_role_labels(self) -> list[str]:
        return [role_label(role) for role in self.default_roles]


# Category labels cached per process; cleared each request and on Category save.
_category_label_cache: dict[str, tuple[str, str, str]] | None = None


def clear_category_cache() -> None:
    global _category_label_cache
    _category_label_cache = None


def category_label(code: str) -> str:
    global _category_label_cache
    if _category_label_cache is None:
        _category_label_cache = {
            c: (uz, en, ru) for c, uz, en, ru in Category.objects.values_list("code", "name_uz", "name_en", "name_ru")
        }
    names = _category_label_cache.get(code)
    return localized(*names) if names else code


def category_choices(include=()) -> list[tuple[str, str]]:
    """Active categories as form choices, plus any codes in ``include``."""
    keep = set(include or ())
    return [(c.code, c.name) for c in Category.objects.all() if c.is_active or c.code in keep]


def offcut_category_codes() -> list[str]:
    return list(Category.objects.filter(supports_offcuts=True).values_list("code", flat=True))


def default_roles_for_category(category: str) -> list[str]:
    roles = Category.objects.filter(code=category).values_list("default_roles", flat=True).first()
    return list(roles or [])


def validate_category_code(value) -> None:
    if not Category.objects.filter(code=value).exists():
        raise ValidationError(_("Noma'lum kategoriya: %(code)s"), params={"code": value})


class BaseMaterial(models.Model):
    name = models.CharField(_("Nomi"), max_length=255)
    category = models.CharField(_("Kategoriya"), max_length=50, validators=[validate_category_code])
    allowed_roles = models.JSONField(
        _("Ruxsat etilgan kasblar"),
        default=list,
        blank=True,
        validators=[validate_worker_role_list],
        help_text="List of UserRoles permitted to view/deduct this material",
    )
    unit_of_measure = models.CharField(_("O'lchov birligi"), max_length=20, choices=MeasurementUnit.choices)
    container_size = models.DecimalField(
        _("Idish hajmi"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Size per container (e.g., 12L or 25L bucket)",
    )

    # Stock thresholds
    minimum_threshold = models.DecimalField(
        _("Minimal qoldiq"),
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )

    # Price tracking (USD). Maintained as a weighted average cost by Kirim entries.
    unit_price_usd = models.DecimalField(
        _("Birlik narxi (USD)"),
        max_digits=12,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0.0000"))],
    )

    is_active = models.BooleanField(
        _("Faol"), default=True, help_text="Archived materials are hidden from workers but keep their history."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("material")
        verbose_name_plural = _("materiallar")
        constraints = [
            models.CheckConstraint(condition=models.Q(unit_price_usd__gte=0), name="material_price_non_negative"),
            models.CheckConstraint(condition=models.Q(minimum_threshold__gte=0), name="material_threshold_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.category})"

    def save(self, *args, **kwargs):
        self.allowed_roles = normalize_roles(self.allowed_roles)
        super().save(*args, **kwargs)

    @property
    def category_short(self) -> str:
        return category_label(self.category)

    @property
    def unit_short(self) -> str:
        return UNIT_SHORT_LABELS.get(self.unit_of_measure, self.unit_of_measure)

    @property
    def requires_integer_quantity(self) -> bool:
        return self.unit_of_measure in INTEGER_UNITS

    @property
    def supports_offcuts(self) -> bool:
        return Category.objects.filter(code=self.category, supports_offcuts=True).exists()

    @property
    def allowed_role_labels(self) -> list[str]:
        return [role_label(role) for role in self.allowed_roles]


class WholeMaterial(models.Model):
    material = models.OneToOneField(BaseMaterial, on_delete=models.CASCADE, related_name="whole_stock")
    quantity = models.DecimalField(
        _("Miqdor"),
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    length_mm = models.IntegerField(_("Uzunligi (mm)"), null=True, blank=True, help_text="Standard sheet length in mm")
    width_mm = models.IntegerField(_("Eni (mm)"), null=True, blank=True, help_text="Standard sheet width in mm")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["material__name"]
        verbose_name = _("butun material")
        verbose_name_plural = _("butun materiallar")
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name="whole_stock_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.material.name}: {self.quantity} {self.material.unit_short}"

    @property
    def total_value_usd(self) -> Decimal:
        return (self.quantity * self.material.unit_price_usd).quantize(CENTS, rounding=ROUND_HALF_UP)

    @property
    def is_below_threshold(self) -> bool:
        return self.quantity < self.material.minimum_threshold

    @property
    def shortfall(self) -> Decimal:
        return max(self.material.minimum_threshold - self.quantity, ZERO)

    @property
    def container_count(self) -> Decimal | None:
        size = self.material.container_size
        if not size:
            return None
        return (self.quantity / size).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    @property
    def sheet_area_mm2(self) -> int | None:
        if self.length_mm and self.width_mm:
            return self.length_mm * self.width_mm
        return None


class LeftoverOffcut(models.Model):
    material = models.ForeignKey(BaseMaterial, on_delete=models.CASCADE, related_name="offcuts")
    length_mm = models.IntegerField(_("Uzunligi (mm)"), validators=[MinValueValidator(1)], help_text="Remaining length in mm")
    width_mm = models.IntegerField(_("Eni (mm)"), validators=[MinValueValidator(1)], help_text="Remaining width in mm")
    quantity = models.IntegerField(_("Soni"), default=1, validators=[MinValueValidator(1)])
    notes = models.TextField(_("Izoh"), blank=True, help_text="Location or description of offcut scrap")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="registered_offcuts"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("qoldiq material")
        verbose_name_plural = _("qoldiq materiallar")
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="offcut_quantity_positive"),
            models.CheckConstraint(
                condition=models.Q(length_mm__gte=1, width_mm__gte=1), name="offcut_dimensions_positive"
            ),
        ]
        indexes = [models.Index(fields=["material", "-created_at"])]

    def __str__(self) -> str:
        return f"Offcut: {self.material.name} ({self.length_mm}x{self.width_mm} mm) - Qty: {self.quantity}"

    @property
    def area_m2(self) -> Decimal:
        return (Decimal(self.length_mm * self.width_mm) / Decimal(1_000_000)).quantize(Decimal("0.001"))

    @property
    def estimated_value_usd(self) -> Decimal | None:
        """
        Informational only: area share of a full sheet x current unit price.

        Offcuts are *not* part of the warehouse valuation; their cost was already
        booked when the parent sheet was withdrawn (Chiqim).
        """
        stock = getattr(self.material, "whole_stock", None)
        if stock is None or not stock.sheet_area_mm2:
            return None
        share = Decimal(self.length_mm * self.width_mm) / Decimal(stock.sheet_area_mm2)
        value = share * self.material.unit_price_usd * self.quantity
        return value.quantize(CENTS, rounding=ROUND_HALF_UP)


class TransactionType(models.TextChoices):
    KIRIM = "KIRIM", _("Kirim")
    CHIQIM = "CHIQIM", _("Chiqim")
    OFFCUT_DEPOSIT = "OFFCUT_DEPOSIT", _("Qoldiq qo'shildi")


class ImmutableLedgerError(Exception):
    """Raised on any attempt to modify or delete an inventory ledger entry."""


class InventoryTransactionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableLedgerError("Inventory transactions are append-only and cannot be updated.")

    def delete(self):
        raise ImmutableLedgerError("Inventory transactions are append-only and cannot be deleted.")

    def kirim(self):
        return self.filter(transaction_type=TransactionType.KIRIM)

    def chiqim(self):
        return self.filter(transaction_type=TransactionType.CHIQIM)


class InventoryTransaction(models.Model):
    """
    Append-only ledger entry.

    Sign convention: ``quantity_changed`` is a signed delta (+ for Kirim and offcut
    deposits, - for Chiqim). ``total_price_usd`` is always the non-negative USD value
    of the movement. Offcut movements carry a value of $0 because the cost of the
    parent sheet is booked when the whole sheet is withdrawn.
    """

    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    # PROTECT (not CASCADE): deleting a material must never erase ledger history.
    material = models.ForeignKey(BaseMaterial, on_delete=models.PROTECT, related_name="transactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transactions")

    quantity_changed = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price_usd = models.DecimalField(max_digits=12, decimal_places=4)
    total_price_usd = models.DecimalField(max_digits=14, decimal_places=2)
    stock_after = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Whole-material balance right after this entry (null for offcut movements).",
    )

    is_offcut = models.BooleanField(default=False)
    offcut_length_mm = models.IntegerField(null=True, blank=True)
    offcut_width_mm = models.IntegerField(null=True, blank=True)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = InventoryTransactionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("ombor harakati")
        verbose_name_plural = _("ombor harakatlari")
        indexes = [
            models.Index(fields=["transaction_type", "created_at"]),
            models.Index(fields=["material", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(total_price_usd__gte=0), name="txn_total_non_negative"),
            models.CheckConstraint(condition=models.Q(unit_price_usd__gte=0), name="txn_unit_price_non_negative"),
            models.CheckConstraint(
                condition=(
                    models.Q(transaction_type=TransactionType.CHIQIM, quantity_changed__lt=0)
                    | (~models.Q(transaction_type=TransactionType.CHIQIM) & models.Q(quantity_changed__gt=0))
                ),
                name="txn_quantity_sign_matches_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_transaction_type_display()} · {self.material.name} · {self.quantity_changed}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableLedgerError("Inventory transactions are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableLedgerError("Inventory transactions are append-only and cannot be deleted.")

    @property
    def quantity_abs(self) -> Decimal:
        return abs(self.quantity_changed)
