import django.core.validators
from django.db import migrations, models

#: The trades the system shipped with as fixed choices, now editable rows.
BUILT_IN_ROLES = [
    # code, uz, en, ru, sort_order
    ("ARRACHI", "Arrachi", "Sawyer", "Пильщик", 10),
    ("KRASKACHI", "Kraskachi", "Painter", "Маляр", 20),
    ("SHKURKACHI", "Shkurkachi", "Sander", "Шлифовщик", 30),
    ("ROVERCHI", "Roverchi", "CNC operator", "Оператор ЧПУ", 40),
    ("SBORKACHI", "Sborkachi", "Assembler", "Сборщик", 50),
]


def seed_roles(apps, schema_editor):
    WorkerRole = apps.get_model("users", "WorkerRole")
    for code, uz, en, ru, order in BUILT_IN_ROLES:
        WorkerRole.objects.get_or_create(
            code=code, defaults={"name_uz": uz, "name_en": en, "name_ru": ru, "sort_order": order}
        )


class Migration(migrations.Migration):
    dependencies = [("users", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="WorkerRole",
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
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="O'chirilsa, ro'yxatdan o'tishda tanlab bo'lmaydi; mavjud ishchilar kasbini saqlaydi.",
                        verbose_name="Faol",
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(default=100, verbose_name="Tartib")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "kasb", "verbose_name_plural": "kasblar", "ordering": ["sort_order", "name_uz"]},
        ),
        migrations.RunPython(seed_roles, migrations.RunPython.noop),
    ]
