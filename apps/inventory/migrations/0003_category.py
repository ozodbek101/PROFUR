import django.core.validators
from django.db import migrations, models

import apps.inventory.models
import apps.users.models

#: The categories the system shipped with as fixed choices, now editable rows.
BUILT_IN_CATEGORIES = [
    # code, uz, en, ru, default roles, supports offcuts, sort_order
    ("SHEET", "List materiallar", "Sheet materials", "Листовые материалы", ["ARRACHI", "ROVERCHI"], True, 10),
    ("LIQUID", "Bo'yoq va suyuqliklar", "Paints and liquids", "Краски и жидкости", ["KRASKACHI"], False, 20),
    ("LINEAR", "Lenta va rulonlar", "Tapes and rolls", "Ленты и рулоны", ["SHKURKACHI", "SBORKACHI"], True, 30),
    ("HARDWARE", "Furnitura", "Hardware", "Фурнитура", ["SBORKACHI"], False, 40),
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model("inventory", "Category")
    BaseMaterial = apps.get_model("inventory", "BaseMaterial")
    for code, uz, en, ru, roles, offcuts, order in BUILT_IN_CATEGORIES:
        Category.objects.get_or_create(
            code=code,
            defaults={
                "name_uz": uz, "name_en": en, "name_ru": ru,
                "default_roles": roles, "supports_offcuts": offcuts, "sort_order": order,
            },
        )
    # Any category code already used by a material must exist as a row.
    for code in BaseMaterial.objects.values_list("category", flat=True).distinct():
        Category.objects.get_or_create(code=code, defaults={"name_uz": code.title(), "sort_order": 900})


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0002_ledger_append_only_trigger"),
        ("users", "0002_workerrole"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name_uz", models.CharField(max_length=100, verbose_name="Nomi (o'zbekcha)")),
                ("name_en", models.CharField(blank=True, max_length=100, verbose_name="Nomi (inglizcha)")),
                ("name_ru", models.CharField(blank=True, max_length=100, verbose_name="Nomi (ruscha)")),
                (
                    "code",
                    models.CharField(
                        max_length=40,
                        unique=True,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^[A-Z][A-Z0-9_]{1,39}$",
                                "Kod lotin bosh harflari, raqamlar va _ dan iborat bo'lsin (masalan, PARDOZCHI).",
                            )
                        ],
                        verbose_name="Kod",
                    ),
                ),
                (
                    "default_roles",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Yangi material uchun kasb belgilanmasa, shu kasblar ko'radi va oladi.",
                        validators=[apps.users.models.validate_worker_role_list],
                        verbose_name="Standart kasblar",
                    ),
                ),
                (
                    "supports_offcuts",
                    models.BooleanField(
                        default=False,
                        help_text="List yoki lenta kabi kesiladigan materiallar uchun: qoldiq (uzunlik × eni) qayd etiladi.",
                        verbose_name="Qoldiq yoziladi",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="O'chirilsa, yangi material uchun tanlab bo'lmaydi; mavjudlari qoladi.",
                        verbose_name="Faol",
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(default=100, verbose_name="Tartib")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "kategoriya",
                "verbose_name_plural": "kategoriyalar",
                "ordering": ["sort_order", "name_uz"],
            },
        ),
        migrations.RunPython(seed_categories, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="basematerial",
            name="category",
            field=models.CharField(
                max_length=50, validators=[apps.inventory.models.validate_category_code], verbose_name="Kategoriya"
            ),
        ),
    ]
