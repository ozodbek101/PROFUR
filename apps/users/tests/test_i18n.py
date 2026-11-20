"""Interface language (UZ / EN / RU) and the show-password eye on the login page."""

import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from apps.inventory.models import category_label
from apps.inventory.tests.factories import make_admin, make_user
from apps.users.models import UserRole, role_label


def choose_language(client, code):
    return client.post(reverse("set_language"), {"language": code, "next": reverse("users:login")})


class LanguageSwitchTests(TestCase):
    def test_default_is_uzbek_even_if_the_browser_prefers_russian(self):
        response = self.client.get(reverse("users:login"), HTTP_ACCEPT_LANGUAGE="ru,en;q=0.8")
        self.assertContains(response, '<html lang="uz">')
        self.assertContains(response, "Tizimga kirish")

    def test_switching_to_russian_and_english_is_remembered_in_a_cookie(self):
        for code, heading in (("ru", "Вход в систему"), ("en", "Sign in"), ("uz", "Tizimga kirish")):
            with self.subTest(language=code):
                response = choose_language(self.client, code)
                self.assertRedirects(response, reverse("users:login"), fetch_redirect_response=False)
                self.assertEqual(self.client.cookies[settings.LANGUAGE_COOKIE_NAME].value, code)

                page = self.client.get(reverse("users:login"))
                self.assertContains(page, f'<html lang="{code}">')
                self.assertContains(page, heading)
                self.assertContains(page, f'value="{code}" class="lang-option" lang="{code}"')

    def test_switch_is_offered_on_the_login_page_and_inside_the_app(self):
        self.assertContains(self.client.get(reverse("users:login")), 'class="lang-switch"')
        self.client.force_login(make_user("arrachi", [UserRole.ARRACHI]))
        self.assertContains(self.client.get(reverse("inventory:home")), 'class="lang-switch"', count=2)

    def test_app_pages_render_in_russian(self):
        self.client.force_login(make_admin())
        make_user("yangi", [UserRole.KRASKACHI], approved=False)  # puts a pending count in the sidebar
        choose_language(self.client, "ru")
        for name, text in (
            ("inventory:dashboard", "Стоимость склада"),
            ("inventory:material_list", "Листовые материалы"),
            ("inventory:category_list", "Категории"),
            ("users:worker_role_list", "Пильщик"),
            ("inventory:reports", "Месячный отчёт"),
        ):
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name)), text)

    def test_category_and_trade_names_follow_the_language(self):
        with translation.override("en"):
            self.assertEqual(category_label("SHEET"), "Sheet materials")
            self.assertEqual(role_label(UserRole.ARRACHI), "Sawyer")
            self.assertEqual(role_label(UserRole.ADMIN), "Administrator")
        with translation.override("ru"):
            self.assertEqual(category_label("LIQUID"), "Краски и жидкости")
            self.assertEqual(role_label(UserRole.ROVERCHI), "Оператор ЧПУ")
        with translation.override("uz"):
            self.assertEqual(category_label("SHEET"), "List materiallar")

    def test_russian_plurals(self):
        with translation.override("ru"):
            forms = [translation.ngettext("%(n)s ishchi", "%(n)s ishchi", n) % {"n": n} for n in (1, 3, 5, 21)]
        self.assertEqual(forms, ["1 рабочий", "3 рабочих", "5 рабочих", "21 рабочий"])

    def test_validation_messages_are_translated(self):
        choose_language(self.client, "en")
        response = self.client.post(reverse("users:login"), {"username": "nobody", "password": "wrong-password"})
        self.assertContains(response, "Wrong username or password.")


class PasswordEyeTests(TestCase):
    def test_login_password_has_a_show_password_button(self):
        response = self.client.get(reverse("users:login"))
        self.assertContains(response, 'class="pw-field"')
        self.assertContains(response, 'class="pw-toggle"')
        self.assertContains(response, 'aria-controls="id_password"')
        self.assertContains(response, "aria-label=\"Parolni ko'rsatish\"")

    def test_registration_has_the_button_on_both_password_fields(self):
        response = self.client.get(reverse("users:register"))
        self.assertContains(response, 'class="pw-toggle"', count=2)


class CatalogFilesTests(TestCase):
    def test_translation_catalogs_are_complete_and_compiled(self):
        root = Path(settings.BASE_DIR)
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "i18n.py"), "check"],
            capture_output=True, text=True, encoding="utf-8", cwd=root,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
