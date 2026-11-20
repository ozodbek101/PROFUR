import re
import unicodedata

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import (
    ADMIN_ROLE,
    LocalizedName,
    User,
    WorkerRole,
    all_role_choices,
    normalize_roles,
    worker_role_choices,
)


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": _("Login yoki parol noto'g'ri."),
        "inactive": _("Bu hisob o'chirilgan. Administratorga murojaat qiling."),
        "pending": _(
            "Hisobingiz hali tasdiqlanmagan. Administrator so'rovingizni ko'rib chiqqach, "
            "tizimga kira olasiz."
        ),
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = _("Login")
        self.fields["username"].widget.attrs.update(
            {"autocapitalize": "none", "autocomplete": "username", "autofocus": True}
        )
        self.fields["password"].label = _("Parol")

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username and password:
            # The auth backend rejects unapproved users outright; detect that case
            # (correct password, not yet approved) so we can show a helpful message.
            user = User._default_manager.filter(username=username).first()
            if (
                user is not None
                and user.is_active
                and not user.is_superuser
                and not user.is_approved
                and user.check_password(password)
            ):
                raise forms.ValidationError(self.error_messages["pending"], code="pending")
        return super().clean()


class WorkerRegistrationForm(UserCreationForm):
    full_name = forms.CharField(label=_("To'liq ism (F.I.Sh.)"), max_length=255)
    roles = forms.MultipleChoiceField(
        label=_("Kasbingiz"),
        choices=(),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Bir nechta kasbni tanlashingiz mumkin."),
        error_messages={"required": _("Kamida bitta kasbni tanlang.")},
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "full_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].choices = worker_role_choices()
        self.fields["username"].label = _("Login")
        self.fields["username"].help_text = _("Faqat lotin harflari, raqamlar va @/./+/-/_ belgilar.")
        self.fields["username"].widget.attrs.update({"autocapitalize": "none", "autocomplete": "username"})
        self.fields["password1"].label = _("Parol")
        self.fields["password1"].help_text = _("Kamida 8 ta belgi; faqat raqamlardan iborat bo'lmasin.")
        self.fields["password2"].label = _("Parolni takrorlang")
        self.fields["password2"].help_text = ""

    def save(self, commit=True):
        user = super().save(commit=False)
        user.full_name = self.cleaned_data["full_name"].strip()
        user.roles = normalize_roles(self.cleaned_data["roles"])
        user.is_approved = False
        user.is_active = True
        if commit:
            user.save()
        return user


class RoleAssignmentForm(forms.ModelForm):
    """Used by admins when reviewing a pending registration."""

    roles = forms.MultipleChoiceField(
        label=_("Rollar"),
        choices=(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": _("Kamida bitta rol belgilang.")},
    )

    class Meta:
        model = User
        fields = ("full_name", "roles")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].choices = all_role_choices(include=self.instance.roles or [])


class UserAdminEditForm(forms.ModelForm):
    """Used by admins to manage an existing account."""

    roles = forms.MultipleChoiceField(
        label=_("Rollar"),
        choices=(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    new_password = forms.CharField(
        label=_("Yangi parol"),
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=_("Ishchi parolini unutgan bo'lsa, shu yerda yangisini o'rnating."),
    )

    class Meta:
        model = User
        fields = ("full_name", "roles", "is_approved", "is_active")
        labels = {"is_approved": _("Tasdiqlangan"), "is_active": _("Faol hisob")}

    def __init__(self, *args, acting_user=None, **kwargs):
        self.acting_user = acting_user
        super().__init__(*args, **kwargs)
        self.fields["roles"].choices = all_role_choices(include=self.instance.roles or [])

    def clean_new_password(self):
        password = self.cleaned_data.get("new_password")
        if password:
            password_validation.validate_password(password, self.instance)
        return password

    def clean(self):
        cleaned = super().clean()
        if self.acting_user is not None and self.instance.pk == self.acting_user.pk:
            if ADMIN_ROLE not in (cleaned.get("roles") or []) and not self.instance.is_superuser:
                self.add_error("roles", _("O'zingizdan administrator rolini olib tashlay olmaysiz."))
            if not cleaned.get("is_active", True) or not cleaned.get("is_approved", True):
                self.add_error(None, _("O'z hisobingizni o'chira yoki tasdiqdan chiqara olmaysiz."))
        if cleaned.get("is_approved") and not cleaned.get("roles"):
            self.add_error("roles", _("Tasdiqlangan foydalanuvchida kamida bitta rol bo'lishi kerak."))
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.roles = normalize_roles(self.cleaned_data.get("roles"))
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            user.save()
        return user


# ---------------------------------------------------------------------------
# Managed lists: worker types (and, in apps.inventory, categories)
# ---------------------------------------------------------------------------
NAME_FIELDS = ("name_uz", "name_en", "name_ru")


class LocalizedNameFormMixin:
    """Labels and placeholders for the three name fields; EN/RU fall back to UZ."""

    name_placeholders: dict[str, str] = {}

    def setup_name_fields(self):
        for field in NAME_FIELDS:
            self.fields[field].widget.attrs.setdefault("maxlength", 100)
            if field in self.name_placeholders:
                self.fields[field].widget.attrs["placeholder"] = self.name_placeholders[field]
        self.fields["name_en"].help_text = _("Bo'sh qolsa, o'zbekcha nomi ko'rsatiladi.")
        self.fields["name_ru"].help_text = _("Bo'sh qolsa, o'zbekcha nomi ko'rsatiladi.")


def unique_code_from(model: type[LocalizedName], text: str, reserved=()) -> str:
    """'Pardozchi usta' -> 'PARDOZCHI_USTA' (made unique with _2, _3 ...; never one of ``reserved``)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_").upper()[:34] or "ITEM"
    if not base[0].isalpha():
        base = f"X_{base}"[:34]
    if len(base) < 2:
        base = f"{base}_X"
    code, n = base, 2
    while code in reserved or model.objects.filter(code=code).exists():
        code, n = f"{base}_{n}", n + 1
    return code


class WorkerRoleForm(LocalizedNameFormMixin, forms.ModelForm):
    name_placeholders = {"name_uz": "Pardozchi", "name_en": "Finisher", "name_ru": "Отделочник"}

    class Meta:
        model = WorkerRole
        fields = ("name_uz", "name_en", "name_ru", "sort_order", "is_active")
        help_texts = {"sort_order": _("Ro'yxatlarda kichik raqam oldinroq turadi.")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_name_fields()
        if not self.instance.pk:
            self.fields.pop("is_active")

    def save(self, commit=True):
        role = super().save(commit=False)
        if not role.code:
            role.code = unique_code_from(WorkerRole, self.cleaned_data["name_uz"], reserved={ADMIN_ROLE})
        if commit:
            role.save()
        return role
