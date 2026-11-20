from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.users.models import WORKER_ROLES, UserRole, normalize_roles

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")


class MaterialCategory(models.TextChoices):
    SHEET = "SHEET", "Sheet & Board Materials (MDF, Fanera, PVC, Shpon)"
    LIQUID = "LIQUID", "Liquids & Paints (Kraska, Lak, Gruntovka)"
    LINEAR = "LINEAR", "Linear Materials (Lenta, Shkurka roll)"
    HARDWARE = "HARDWARE", "Hardware & Fittings (Furnitura, Samarez, Handles, Legs)"


class MeasurementUnit(models.TextChoices):
    SHEET_COUNT = "SHEET", "Sheet Count (Dona)"
    LITER = "LITER", "Liter (L)"
    KILOGRAM = "KG", "Kilogram (kg)"
    METER = "METER", "Meter (m)"
    CENTIMETER = "CM", "Centimeter (cm)"
    PIECE = "PIECE", "Unit Piece (Dona)"


#: Short Uzbek category names for the UI (the TextChoices labels are the long bilingual ones).
CATEGORY_SHORT_LABELS = {
    MaterialCategory.SHEET: "List materiallar",
    MaterialCategory.LIQUID: "Bo'yoq va suyuqliklar",
    MaterialCategory.LINEAR: "Lenta va rulonlar",
    MaterialCategory.HARDWARE: "Furnitura",
}

#: Short unit labels for compact tables and buttons.
UNIT_SHORT_LABELS = {
    MeasurementUnit.SHEET_COUNT: "dona",
    MeasurementUnit.LITER: "L",
    MeasurementUnit.KILOGRAM: "kg",
    MeasurementUnit.METER: "m",
    MeasurementUnit.CENTIMETER: "sm",
    MeasurementUnit.PIECE: "dona",
}

#: Units that can only move in whole numbers (you cannot take 1.5 hinges).
INTEGER_UNITS = frozenset({MeasurementUnit.SHEET_COUNT, MeasurementUnit.PIECE})

#: Default trade access per category; admins can override per material.
DEFAULT_CATEGORY_ROLES: dict[str, list[str]] = {
    MaterialCategory.SHEET: [UserRole.ARRACHI, UserRole.ROVERCHI],
    MaterialCategory.LIQUID: [UserRole.KRASKACHI],
    MaterialCategory.LINEAR: [UserRole.SHKURKACHI, UserRole.SBORKACHI],
    MaterialCategory.HARDWARE: [UserRole.SBORKACHI],
}

#: Categories for which leftover offcuts (length x width) make sense.
OFFCUT_CATEGORIES = frozenset({MaterialCategory.SHEET, MaterialCategory.LINEAR})


def default_roles_for_category(category: str) -> list[str]:
    return [str(role) for role in DEFAULT_CATEGORY_ROLES.get(category, [])]


def validate_worker_role_list(value) -> None:
    if not isinstance(value, list):
        raise ValidationError("Ruxsat etilgan kasblar ro'yxat (list) bo'lishi kerak.")
    unknown = [role for role in value if role not in WORKER_ROLES]
    if unknown:
        raise ValidationError("Noma'lum kasb(lar): %(roles)s", params={"roles": ", ".join(map(str, unknown))})


class BaseMaterial(models.Model):
    name = models.CharField("Nomi", max_length=255)
    category = models.CharField("Kategoriya", max_length=50, choices=MaterialCategory.choices)
    allowed_roles = models.JSONField(
        "Ruxsat etilgan kasblar",
        default=list,
        blank=True,
        validators=[validate_worker_role_list],
        help_text="List of UserRoles permitted to view/deduct this material",
    )
    unit_of_measure = models.CharField("O'lchov birligi", max_length=20, choices=MeasurementUnit.choices)
    container_size = models.DecimalField(
        "Idish hajmi",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Size per container (e.g., 12L or 25L bucket)",
    )

    # Stock thresholds
    minimum_threshold = models.DecimalField(
        "Minimal qoldiq",
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )

    # Price tracking (USD). Maintained as a weighted average cost by Kirim entries.
    unit_price_usd = models.DecimalField(
        "Birlik narxi (USD)",
        max_digits=12,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0.0000"))],
    )

    is_active = models.BooleanField(
        "Faol", default=True, help_text="Archived materials are hidden from workers but keep their history."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "material"
        verbose_name_plural = "materiallar"
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
        return CATEGORY_SHORT_LABELS.get(self.category, self.category)

    @property
    def unit_short(self) -> str:
        return UNIT_SHORT_LABELS.get(self.unit_of_measure, self.unit_of_measure)

    @property
    def requires_integer_quantity(self) -> bool:
        return self.unit_of_measure in INTEGER_UNITS

    @property
    def supports_offcuts(self) -> bool:
        return self.category in OFFCUT_CATEGORIES

    @property
    def allowed_role_labels(self) -> list[str]:
        return [UserRole(role).label for role in self.allowed_roles if role in UserRole.values]


class WholeMaterial(models.Model):
    material = models.OneToOneField(BaseMaterial, on_delete=models.CASCADE, related_name="whole_stock")
    quantity = models.DecimalField(
        "Miqdor",
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    length_mm = models.IntegerField("Uzunligi (mm)", null=True, blank=True, help_text="Standard sheet length in mm")
    width_mm = models.IntegerField("Eni (mm)", null=True, blank=True, help_text="Standard sheet width in mm")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["material__name"]
        verbose_name = "butun material"
        verbose_name_plural = "butun materiallar"
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
    length_mm = models.IntegerField("Uzunligi (mm)", validators=[MinValueValidator(1)], help_text="Remaining length in mm")
    width_mm = models.IntegerField("Eni (mm)", validators=[MinValueValidator(1)], help_text="Remaining width in mm")
    quantity = models.IntegerField("Soni", default=1, validators=[MinValueValidator(1)])
    notes = models.TextField("Izoh", blank=True, help_text="Location or description of offcut scrap")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="registered_offcuts"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "qoldiq material"
        verbose_name_plural = "qoldiq materiallar"
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
    KIRIM = "KIRIM", "Stock Arrival (Kirim)"
    CHIQIM = "CHIQIM", "Worker Withdrawal (Chiqim)"
    OFFCUT_DEPOSIT = "OFFCUT_DEPOSIT", "Offcut Deposit (Qoldiq)"


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
        verbose_name = "ombor harakati"
        verbose_name_plural = "ombor harakatlari"
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
