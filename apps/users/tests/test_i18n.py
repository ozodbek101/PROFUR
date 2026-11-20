"""Interface language: Uzbek by default, Russian or English when the user picks it in the switcher."""

import datetime as dt

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from apps.inventory.models import (
    Category,
    MaterialCategory,
    MeasurementUnit,
    category_label,
    clear_category_cache,
    unit_short_label,
)
from apps.inventory.templatetags.wms import month_name
from apps.inventory.tests.factories import make_admin, make_material, make_user
from apps.users.models import UserRole, WorkerRole, clear_role_cache, role_label


class LanguageSelectionTests(TestCase):
    def get_login(self, language=None, **headers):
        if language:
            self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
        return self.client.get(reverse("users:login"), **headers)

    def test_default_is_uzbek_even_when_the_browser_prefers_russian(self):
        response = self.get_login(HTTP_ACCEPT_LANGUAGE="ru-RU,ru;q=0.9")
        self.assertContains(response, '<html lang="uz"')
        self.assertContains(response, "Tizimga kirish")

    def test_cookie_selects_russian(self):
        response = self.get_login("ru")
        self.assertContains(response, '<html lang="ru"')
        self.assertContains(response, "Вход в систему")
        self.assertNotContains(response, "Tizimga kirish")

    def test_cookie_selects_english(self):
        response = self.get_login("en")
        self.assertContains(response, '<html lang="en"')
        self.assertContains(response, "Log in")
        self.assertNotContains(response, "Tizimga kirish")

    def test_unknown_language_cookie_falls_back_to_uzbek(self):
        response = self.get_login("de")
        self.assertContains(response, '<html lang="uz"')

    def test_switcher_is_shown_on_the_login_page(self):
        response = self.get_login()
        self.assertContains(response, f'action="{reverse("set_language")}"')
        for code in ("uz", "ru", "en"):
            self.assertContains(response, f'name="language" value="{code}"')

    def test_switching_stores_the_choice_in_a_cookie(self):
        response = self.client.post(reverse("set_language"), {"language": "ru", "next": reverse("users:login")})
        self.assertRedirects(response, reverse("users:login"), fetch_redirect_response=False)
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "ru")
        self.assertContains(self.client.get(reverse("users:login")), '<html lang="ru"')


class TranslatedNamesTests(TestCase):
    """Built-in trades, categories, units and months are translated; names people typed are not."""

    def setUp(self):
        clear_role_cache()
        clear_category_cache()
        self.addCleanup(clear_role_cache)
        self.addCleanup(clear_category_cache)

    def test_built_in_names_follow_the_language(self):
        november = dt.date(2026, 11, 1)
        expected = {
            "uz": ("Kraskachi", "Furnitura", "dona", "noyabr"),
            "ru": ("Маляр", "Фурнитура", "шт.", "ноябрь"),
            "en": ("Painter", "Hardware", "pcs", "November"),
        }
        for language, (trade, category, unit, month) in expected.items():
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(role_label(UserRole.KRASKACHI), trade)
                self.assertEqual(category_label(MaterialCategory.HARDWARE), category)
                self.assertEqual(unit_short_label(MeasurementUnit.PIECE), unit)
                self.assertEqual(month_name(november), month)

    def test_trades_and_categories_added_by_admins_are_shown_as_typed(self):
        WorkerRole.objects.create(code="PARDOZCHI", name="Pardozchi", sort_order=60)
        Category.objects.create(code="OYNA", name="Oyna va ko'zgu", sort_order=50)
        clear_role_cache()
        clear_category_cache()
        with translation.override("ru"):
            self.assertEqual(role_label("PARDOZCHI"), "Pardozchi")
            self.assertEqual(category_label("OYNA"), "Oyna va ko'zgu")

    def test_registration_lists_trades_in_the_chosen_language(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "ru"
        response = self.client.get(reverse("users:register"))
        self.assertContains(response, "Маляр")
        self.assertNotContains(response, "Kraskachi")

    def test_translated_name_of_a_built_in_trade_is_not_accepted_as_a_new_trade(self):
        self.client.force_login(make_admin())
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "ru"
        before = WorkerRole.objects.count()
        response = self.client.post(reverse("users:worker_role_create"), {"name": "маляр"})
        self.assertContains(response, "Такая профессия уже есть.")
        self.assertEqual(WorkerRole.objects.count(), before)

    def test_translated_name_of_a_built_in_category_selects_it(self):
        from apps.inventory.forms import OTHER_CATEGORY, MaterialForm

        with translation.override("ru"):
            form = MaterialForm(data={
                "name": "Petlya", "category": OTHER_CATEGORY, "new_category": "Фурнитура",
                "unit_of_measure": MeasurementUnit.PIECE, "minimum_threshold": "0",
            })
            self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["category"], MaterialCategory.HARDWARE)
        self.assertEqual(form.pending_category_name, "")

    def test_material_and_person_names_are_never_translated(self):
        worker = make_user("otkir", [UserRole.KRASKACHI], full_name="O'tkir Karimov")
        make_material("Kraska oq 12L", MaterialCategory.LIQUID, MeasurementUnit.LITER)
        self.client.force_login(worker)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        response = self.client.get(reverse("inventory:home"))
        self.assertContains(response, "Kraska oq 12L")
        self.assertContains(response, "O&#x27;tkir Karimov")
        self.assertContains(response, "Paints and liquids")
