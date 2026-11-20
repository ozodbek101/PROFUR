import re
import unicodedata

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User, UserRole, WorkerRole, all_role_choices, normalize_roles, worker_role_choices


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Login yoki parol noto'g'ri.",
        "inactive": "Bu hisob o'chirilgan. Administratorga murojaat qiling.",
        "pending": (
            "Hisobingiz hali tasdiqlanmagan. Administrator so'rovingizni ko'rib chiqqach, "
            "tizimga kira olasiz."
        ),
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "Login"
        self.fields["username"].widget.attrs.update(
            {"autocapitalize": "none", "autocomplete": "username", "autofocus": True}
        )
        self.fields["password"].label = "Parol"

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
    full_name = forms.CharField(label="To'liq ism (F.I.Sh.)", max_length=255)
    roles = forms.MultipleChoiceField(
        label="Kasbingiz",
        choices=worker_role_choices,
        widget=forms.CheckboxSelectMultiple,
        help_text="Bir nechta kasbni tanlashingiz mumkin.",
        error_messages={"required": "Kamida bitta kasbni tanlang."},
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "full_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Login"
        self.fields["username"].help_text = "Faqat lotin harflari, raqamlar va @/./+/-/_ belgilar."
        self.fields["username"].widget.attrs.update({"autocapitalize": "none", "autocomplete": "username"})
        self.fields["password1"].label = "Parol"
        self.fields["password1"].help_text = "Kamida 8 ta belgi; faqat raqamlardan iborat bo'lmasin."
        self.fields["password2"].label = "Parolni takrorlang"
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
        label="Rollar",
        choices=all_role_choices,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Kamida bitta rol belgilang."},
    )

    class Meta:
        model = User
        fields = ("full_name", "roles")


class UserAdminEditForm(forms.ModelForm):
    """Used by admins to manage an existing account."""

    roles = forms.MultipleChoiceField(
        label="Rollar",
        choices=all_role_choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    new_password = forms.CharField(
        label="Yangi parol",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Ishchi parolini unutgan bo'lsa, shu yerda yangisini o'rnating.",
    )

    class Meta:
        model = User
        fields = ("full_name", "roles", "is_approved", "is_active")
        labels = {"is_approved": "Tasdiqlangan", "is_active": "Faol hisob"}

    def __init__(self, *args, acting_user=None, **kwargs):
        self.acting_user = acting_user
        super().__init__(*args, **kwargs)

    def clean_new_password(self):
        password = self.cleaned_data.get("new_password")
        if password:
            password_validation.validate_password(password, self.instance)
        return password

    def clean(self):
        cleaned = super().clean()
        if self.acting_user is not None and self.instance.pk == self.acting_user.pk:
            if UserRole.ADMIN not in (cleaned.get("roles") or []) and not self.instance.is_superuser:
                self.add_error("roles", "O'zingizdan administrator rolini olib tashlay olmaysiz.")
            if not cleaned.get("is_active", True) or not cleaned.get("is_approved", True):
                self.add_error(None, "O'z hisobingizni o'chira yoki tasdiqdan chiqara olmaysiz.")
        if cleaned.get("is_approved") and not cleaned.get("roles"):
            self.add_error("roles", "Tasdiqlangan foydalanuvchida kamida bitta rol bo'lishi kerak.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.roles = normalize_roles(self.cleaned_data.get("roles"))
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            user.save()
        return user


class WorkerRoleForm(forms.ModelForm):
    """Admin: add a new trade (kasb). The code is generated from the name and never changes."""

    class Meta:
        model = WorkerRole
        fields = ("name",)
        labels = {"name": "Kasb nomi"}
        help_texts = {"name": "Masalan: Pardozchi. Ishchilar ro'yxatdan o'tishda shu nomni ko'radi."}

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if WorkerRole.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("Bunday kasb allaqachon bor.")
        return name

    def save(self, commit=True):
        role = super().save(commit=False)
        role.code = trade_code_from(role.name)
        last = WorkerRole.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
        role.sort_order = last + 10
        if commit:
            role.save()
        return role


def unique_code(name: str, is_taken, fallback: str, max_length: int = 34) -> str:
    """'Pardozchi usta' -> 'PARDOZCHI_USTA', with _2, _3 ... appended while ``is_taken(code)``."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_").upper()[:max_length] or fallback
    if not base[0].isalpha():
        base = f"{fallback}_{base}"[:max_length]
    code, n = base, 2
    while is_taken(code):
        code, n = f"{base}_{n}", n + 1
    return code


def trade_code_from(name: str) -> str:
    """A unique trade code for ``name``; never 'ADMIN'."""
    return unique_code(
        name, lambda code: code == UserRole.ADMIN or WorkerRole.objects.filter(code=code).exists(), "KASB"
    )
