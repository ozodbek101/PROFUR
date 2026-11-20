import datetime as dt
from decimal import Decimal

from django import forms
from django.core.validators import MaxValueValidator

from apps.users.models import WORKER_ROLE_CHOICES, User

from .models import (
    BaseMaterial,
    MaterialCategory,
    MeasurementUnit,
    TransactionType,
    WholeMaterial,
)
from .selectors import offcut_capable_materials

MAX_MM = 100_000


class MaterialChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: BaseMaterial) -> str:
        return f"{obj.name} ({obj.unit_short})"


class MaterialForm(forms.ModelForm):
    """Admin: create or edit a material card (and its standard sheet size)."""

    allowed_roles = forms.MultipleChoiceField(
        label="Qaysi kasblar ko'ra oladi va oladi",
        choices=WORKER_ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Bo'sh qoldirilsa, kategoriya bo'yicha standart kasblar belgilanadi.",
    )
    length_mm = forms.IntegerField(
        label="List uzunligi (mm)", required=False, min_value=1, max_value=MAX_MM,
        help_text="Faqat list materiallar uchun, masalan 2750.",
    )
    width_mm = forms.IntegerField(
        label="List eni (mm)", required=False, min_value=1, max_value=MAX_MM,
        help_text="Masalan 1830.",
    )

    class Meta:
        model = BaseMaterial
        fields = (
            "name",
            "category",
            "unit_of_measure",
            "container_size",
            "minimum_threshold",
            "allowed_roles",
            "is_active",
        )
        help_texts = {
            "container_size": "Masalan, 12 litrli chelak uchun 12. Kirimda idish soni bilan hisoblash uchun.",
            "minimum_threshold": "Miqdor shundan kam bo'lsa, xarid ro'yxatida ko'rinadi.",
            "is_active": "O'chirilsa, ishchilar materialni ko'rmaydi; tarix saqlanadi.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        stock = getattr(self.instance, "whole_stock", None) if self.instance.pk else None
        if stock is not None:
            self.fields["length_mm"].initial = stock.length_mm
            self.fields["width_mm"].initial = stock.width_mm
        if not self.instance.pk:
            self.fields.pop("is_active")

    def clean(self):
        cleaned = super().clean()
        length, width = cleaned.get("length_mm"), cleaned.get("width_mm")
        if bool(length) != bool(width):
            self.add_error("width_mm" if length else "length_mm", "Uzunlik va enni birga kiriting.")
        if cleaned.get("category") == MaterialCategory.LIQUID and cleaned.get("unit_of_measure") in (
            MeasurementUnit.SHEET_COUNT,
            MeasurementUnit.METER,
            MeasurementUnit.CENTIMETER,
        ):
            self.add_error("unit_of_measure", "Suyuqliklar uchun litr, kg yoki dona tanlang.")
        return cleaned

    def save_stock_dimensions(self, material: BaseMaterial) -> None:
        stock, _ = WholeMaterial.objects.get_or_create(material=material)
        stock.length_mm = self.cleaned_data.get("length_mm")
        stock.width_mm = self.cleaned_data.get("width_mm")
        stock.save(update_fields=["length_mm", "width_mm", "updated_at"])


class KirimForm(forms.Form):
    """Admin: record a stock arrival with either the batch total or the per-unit price."""

    PRICE_TOTAL = "total"
    PRICE_UNIT = "unit"

    material = MaterialChoiceField(
        queryset=BaseMaterial.objects.filter(is_active=True), label="Material", empty_label="Materialni tanlang"
    )
    containers = forms.DecimalField(
        label="Idishlar soni",
        required=False,
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"x-model.number": "containers", "inputmode": "decimal"}),
        help_text="Masalan, 5 chelak. Miqdor idish hajmiga ko'paytirib hisoblanadi.",
    )
    quantity = forms.DecimalField(
        label="Miqdor", required=False, min_value=Decimal("0.01"), max_digits=12, decimal_places=2
    )
    price_mode = forms.ChoiceField(
        label="Narx turi",
        choices=[(PRICE_TOTAL, "Umumiy partiya narxi"), (PRICE_UNIT, "Bir birlik narxi")],
        widget=forms.RadioSelect(attrs={"x-model": "mode"}),
        initial=PRICE_TOTAL,
    )
    price_usd = forms.DecimalField(
        label="Narx (USD $)", min_value=Decimal("0"), max_digits=14, decimal_places=4
    )
    notes = forms.CharField(
        label="Izoh",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Yetkazib beruvchi, faktura raqami..."}),
    )

    def clean(self):
        cleaned = super().clean()
        material: BaseMaterial | None = cleaned.get("material")
        containers = cleaned.get("containers")
        quantity = cleaned.get("quantity")
        if material and containers:
            if not material.container_size:
                self.add_error("containers", "Bu material uchun idish hajmi belgilanmagan.")
            else:
                quantity = (containers * material.container_size).quantize(Decimal("0.01"))
                cleaned["quantity"] = quantity
        if not quantity and not self.has_error("containers"):
            self.add_error("quantity", "Miqdorni yoki idishlar sonini kiriting.")
        return cleaned

    def service_kwargs(self) -> dict:
        data = self.cleaned_data
        price_key = "total_price_usd" if data["price_mode"] == self.PRICE_TOTAL else "unit_price_usd"
        return {
            "material": data["material"],
            "quantity": data["quantity"],
            price_key: data["price_usd"],
            "notes": data.get("notes", ""),
        }


class WithdrawWholeForm(forms.Form):
    quantity = forms.DecimalField(
        label="Qancha oldingiz?", min_value=Decimal("0.01"), max_digits=12, decimal_places=2
    )
    notes = forms.CharField(
        label="Izoh",
        required=False,
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "Buyurtma yoki mijoz nomi"}),
    )

    def __init__(self, *args, stock: WholeMaterial, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["quantity"]
        field.widget.attrs.update(
            {"inputmode": "decimal", "autofocus": True, "max": stock.quantity, "x-model.number": "q"}
        )
        if stock.material.requires_integer_quantity:
            field.widget.attrs.update({"step": "1", "inputmode": "numeric"})
            field.initial = 1


class OffcutForm(forms.Form):
    material = MaterialChoiceField(queryset=BaseMaterial.objects.none(), label="Material", empty_label="Materialni tanlang")
    length_mm = forms.IntegerField(label="Uzunligi (mm)", min_value=1, max_value=MAX_MM)
    width_mm = forms.IntegerField(label="Eni (mm)", min_value=1, max_value=MAX_MM)
    quantity = forms.IntegerField(label="Soni (dona)", min_value=1, max_value=1000, initial=1)
    notes = forms.CharField(
        label="Joylashuvi / izoh",
        required=False,
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "Masalan: 2-stellaj, yuqori polka"}),
    )

    def __init__(self, *args, user: User, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = offcut_capable_materials(user).select_related("whole_stock")
        self.fields["material"].widget.attrs.update({"x-model": "material"})
        for name, model in (("length_mm", "length"), ("width_mm", "width"), ("quantity", "pieces")):
            self.fields[name].widget.attrs.update({"inputmode": "numeric", "x-model.number": model})


class WithdrawOffcutForm(forms.Form):
    quantity = forms.IntegerField(label="Necha dona oldingiz?", min_value=1, initial=1)
    notes = forms.CharField(label="Izoh", required=False, max_length=500)

    def __init__(self, *args, max_quantity: int, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["quantity"]
        field.max_value = max_quantity
        field.validators.append(MaxValueValidator(max_quantity))
        field.widget.attrs.update({"max": max_quantity, "inputmode": "numeric", "x-model.number": "q"})


class ReportFilterForm(forms.Form):
    month = forms.CharField(
        label="Oy", required=False, widget=forms.TextInput(attrs={"type": "month"})
    )
    transaction_type = forms.ChoiceField(
        label="Harakat turi", required=False, choices=[("", "Barchasi"), *TransactionType.choices]
    )
    category = forms.ChoiceField(
        label="Kategoriya", required=False, choices=[("", "Barchasi"), *MaterialCategory.choices]
    )
    user = forms.ModelChoiceField(
        label="Ishchi", required=False, queryset=User.objects.order_by("full_name", "username"), empty_label="Barchasi"
    )
    material = MaterialChoiceField(
        label="Material", required=False, queryset=BaseMaterial.objects.order_by("name"), empty_label="Barchasi"
    )

    def clean_month(self) -> dt.date | None:
        value = self.cleaned_data.get("month")
        if not value:
            return None
        try:
            return dt.datetime.strptime(value, "%Y-%m").date()
        except ValueError as exc:
            raise forms.ValidationError("Oyni YYYY-MM ko'rinishida kiriting.") from exc

    def selector_kwargs(self) -> dict:
        data = self.cleaned_data if self.is_valid() else {}
        return {
            "month": data.get("month"),
            "category": data.get("category", ""),
            "transaction_type": data.get("transaction_type", ""),
            "user_id": data["user"].pk if data.get("user") else None,
            "material_id": data["material"].pk if data.get("material") else None,
        }
