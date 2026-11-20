"""Admin-managed material categories and worker trades (kasblar)."""

from django.test import TestCase
from django.urls import reverse

from apps.inventory.forms import MaterialForm
from apps.inventory.models import Category, MeasurementUnit, category_label, offcut_category_codes
from apps.users.models import User, UserRole, WorkerRole, worker_role_codes

from .factories import PASSWORD, make_admin, make_material, make_user


class CategoryManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        cls.worker = make_user("arrachi", [UserRole.ARRACHI])

    def setUp(self):
        self.client.force_login(self.admin)

    def create_category(self, **overrides):
        data = {
            "name_uz": "Shisha va oyna",
            "name_en": "Glass and mirrors",
            "name_ru": "Стекло и зеркала",
            "default_roles": [UserRole.SBORKACHI],
            "supports_offcuts": "on",
            "sort_order": 50,
        }
        data.update(overrides)
        return self.client.post(reverse("inventory:category_create"), data)

    def test_seeded_categories_exist(self):
        self.assertEqual(
            list(Category.objects.values_list("code", flat=True)), ["SHEET", "LIQUID", "LINEAR", "HARDWARE"]
        )

    def test_admin_adds_a_category_with_generated_code(self):
        response = self.create_category()

        self.assertRedirects(response, reverse("inventory:category_list"))
        category = Category.objects.get(code="SHISHA_VA_OYNA")
        self.assertEqual(category.name_en, "Glass and mirrors")
        self.assertEqual(category.default_roles, [UserRole.SBORKACHI])
        self.assertTrue(category.supports_offcuts)
        self.assertIn("SHISHA_VA_OYNA", offcut_category_codes())
        self.assertContains(self.client.get(reverse("inventory:category_list")), "Shisha va oyna")

    def test_same_name_gets_a_unique_code(self):
        self.create_category()
        self.create_category()
        self.assertTrue(Category.objects.filter(code="SHISHA_VA_OYNA_2").exists())

    def test_new_category_is_offered_on_the_material_form_and_applies_default_roles(self):
        self.create_category(supports_offcuts="")
        self.assertIn("SHISHA_VA_OYNA", dict(MaterialForm().fields["category"].choices))

        material = make_material("Oyna 4 mm", "SHISHA_VA_OYNA", MeasurementUnit.PIECE)
        self.assertEqual(material.allowed_roles, [UserRole.SBORKACHI])
        self.assertFalse(material.supports_offcuts)

    def test_editing_keeps_the_code_and_deactivating_hides_it_from_new_materials(self):
        self.create_category()
        category = Category.objects.get(code="SHISHA_VA_OYNA")
        material = make_material("Oyna 4 mm", category.code, MeasurementUnit.PIECE)

        response = self.client.post(
            reverse("inventory:category_edit", args=[category.pk]),
            {"name_uz": "Oynalar", "name_en": "", "name_ru": "", "default_roles": [], "sort_order": 50},
        )

        self.assertRedirects(response, reverse("inventory:category_list"))
        category.refresh_from_db()
        self.assertEqual((category.code, category.name_uz, category.is_active), ("SHISHA_VA_OYNA", "Oynalar", False))
        self.assertNotIn(category.code, dict(MaterialForm().fields["category"].choices))
        # A material already in the category can still be edited and keeps its label.
        self.assertIn(category.code, dict(MaterialForm(instance=material).fields["category"].choices))
        self.assertEqual(category_label(category.code), "Oynalar")

    def test_unknown_category_is_rejected(self):
        form = MaterialForm(data={"name": "X", "category": "NOPE", "unit_of_measure": MeasurementUnit.PIECE})
        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)

    def test_workers_cannot_manage_categories(self):
        self.client.force_login(self.worker)
        for url in (reverse("inventory:category_list"), reverse("inventory:category_create")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)


class WorkerRoleManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()

    def add_role(self, **overrides):
        data = {"name_uz": "Pardozchi", "name_en": "Finisher", "name_ru": "Отделочник", "sort_order": 60}
        data.update(overrides)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("users:worker_role_create"), data)
        self.client.logout()
        return response

    def test_admin_adds_a_trade_that_workers_can_register_with(self):
        response = self.add_role()
        self.assertRedirects(response, reverse("users:worker_role_list"), fetch_redirect_response=False)
        self.assertIn("PARDOZCHI", worker_role_codes())

        register = self.client.get(reverse("users:register"))
        self.assertContains(register, "Pardozchi")

        self.client.post(reverse("users:register"), {
            "username": "jasur", "full_name": "Jasur Aliyev", "roles": ["PARDOZCHI"],
            "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertEqual(User.objects.get(username="jasur").roles, ["PARDOZCHI"])

    def test_new_trade_sees_only_materials_allowed_for_it(self):
        self.add_role()
        worker = make_user("jasur", ["PARDOZCHI"])
        make_material("Lak", "LIQUID", MeasurementUnit.LITER, allowed_roles=["PARDOZCHI"])
        make_material("MDF 16 mm")  # SHEET: sawyers and CNC operators only

        self.client.force_login(worker)
        response = self.client.get(reverse("inventory:home"))
        self.assertContains(response, "Lak")
        self.assertNotContains(response, "MDF 16 mm")

    def test_inactive_trade_is_not_offered_on_registration(self):
        self.add_role()
        WorkerRole.objects.filter(code="PARDOZCHI").update(is_active=False)
        register = self.client.get(reverse("users:register"))
        self.assertNotContains(register, "Pardozchi")

    def test_admin_role_cannot_be_created_as_a_trade(self):
        self.add_role(name_uz="Admin")
        self.assertEqual(WorkerRole.objects.get(name_uz="Admin").code, "ADMIN_2")

    def test_list_shows_seeded_trades_with_worker_counts(self):
        make_user("arrachi", [UserRole.ARRACHI])
        self.client.force_login(self.admin)
        response = self.client.get(reverse("users:worker_role_list"))
        self.assertContains(response, "Arrachi")
        self.assertContains(response, "Sborkachi")
        self.assertEqual(
            {r.code: r.user_count for r in response.context["roles"]}[UserRole.ARRACHI], 1
        )
