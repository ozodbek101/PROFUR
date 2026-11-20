"""REST API: role isolation, price hiding, stock operations, Kirim and the dashboard."""

from decimal import Decimal

from django.test import TestCase

from apps.inventory import services
from apps.inventory.models import InventoryTransaction, LeftoverOffcut, MaterialCategory, MeasurementUnit
from apps.users.models import UserRole

from .factories import make_admin, make_material, make_user, stock_up


class ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        cls.arrachi = make_user("arrachi", [UserRole.ARRACHI])
        cls.kraskachi = make_user("kraskachi", [UserRole.KRASKACHI])
        cls.mdf = make_material("MDF 16 mm", minimum=12)
        cls.paint = make_material("Akril", MaterialCategory.LIQUID, MeasurementUnit.LITER)
        stock_up(cls.mdf, cls.admin, 10, unit_price="38.50")
        stock_up(cls.paint, cls.admin, 12, unit_price="4.35")
        cls.offcut = services.register_offcut(material=cls.mdf, user=cls.arrachi, length_mm=900, width_mm=400, quantity=2)

    def post(self, url, data):
        return self.client.post(url, data, content_type="application/json")


class StockApiTests(ApiTestCase):
    def test_anonymous_requests_are_refused(self):
        self.assertEqual(self.client.get("/api/whole-materials/").status_code, 403)

    def test_workers_list_only_their_materials_without_prices(self):
        self.client.force_login(self.kraskachi)
        rows = self.client.get("/api/whole-materials/").json()["results"]
        self.assertEqual([row["material"]["name"] for row in rows], ["Akril"])
        self.assertNotIn("unit_price_usd", rows[0])
        self.assertNotIn("total_value_usd", rows[0])
        self.assertEqual(self.client.get("/api/offcuts/").json()["results"], [])

    def test_admin_sees_prices_and_line_values(self):
        self.client.force_login(self.admin)
        rows = {row["material"]["name"]: row for row in self.client.get("/api/whole-materials/").json()["results"]}
        self.assertEqual(rows["MDF 16 mm"]["total_value_usd"], "385.00")
        self.assertTrue(rows["MDF 16 mm"]["is_below_threshold"])

    def test_withdraw_whole_material(self):
        self.client.force_login(self.arrachi)
        response = self.post(f"/api/whole-materials/{self.mdf.whole_stock.pk}/withdraw/", {"quantity": "4", "notes": "API"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["quantity_changed"], "-4.00")
        self.assertNotIn("total_price_usd", response.json())
        self.mdf.whole_stock.refresh_from_db()
        self.assertEqual(self.mdf.whole_stock.quantity, Decimal("6"))

    def test_withdrawing_too_much_is_a_400(self):
        self.client.force_login(self.arrachi)
        response = self.post(f"/api/whole-materials/{self.mdf.whole_stock.pk}/withdraw/", {"quantity": "50"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.json())

    def test_another_trades_stock_is_a_404(self):
        self.client.force_login(self.kraskachi)
        response = self.post(f"/api/whole-materials/{self.mdf.whole_stock.pk}/withdraw/", {"quantity": "1"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(f"/api/offcuts/{self.offcut.pk}/").status_code, 404)

    def test_register_and_take_offcuts(self):
        self.client.force_login(self.arrachi)
        response = self.post("/api/offcuts/", {"material_id": self.mdf.pk, "length_mm": 640, "width_mm": 520, "quantity": 1})
        self.assertEqual(response.status_code, 201, response.content)
        new_id = response.json()["id"]

        response = self.post(f"/api/offcuts/{new_id}/withdraw/", {"quantity": 1})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(LeftoverOffcut.objects.filter(pk=new_id).exists())

        response = self.post(f"/api/offcuts/{self.offcut.pk}/withdraw/", {"quantity": 5})
        self.assertEqual(response.status_code, 400)

    def test_offcut_for_another_trades_material_is_refused(self):
        self.client.force_login(self.kraskachi)
        response = self.post("/api/offcuts/", {"material_id": self.mdf.pk, "length_mm": 640, "width_mm": 520})
        self.assertEqual(response.status_code, 400)
        self.assertIn("material_id", response.json())

    def test_oversized_offcut_is_a_400(self):
        self.client.force_login(self.arrachi)
        response = self.post("/api/offcuts/", {"material_id": self.mdf.pk, "length_mm": 4000, "width_mm": 520})
        self.assertEqual(response.status_code, 400)


class AdminApiTests(ApiTestCase):
    def test_kirim_is_admin_only(self):
        self.client.force_login(self.arrachi)
        response = self.post("/api/kirim/", {"material_id": self.mdf.pk, "quantity": "5", "total_price_usd": "200"})
        self.assertEqual(response.status_code, 403)

    def test_kirim_with_total_price(self):
        self.client.force_login(self.admin)
        response = self.post("/api/kirim/", {"material_id": self.mdf.pk, "quantity": "5", "total_price_usd": "200"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["unit_price_usd"], "40.0000")
        self.mdf.refresh_from_db()
        self.assertEqual(self.mdf.unit_price_usd, Decimal("39.0000"))  # (385 + 200) / 15

    def test_kirim_needs_exactly_one_price(self):
        self.client.force_login(self.admin)
        both = {"material_id": self.mdf.pk, "quantity": "1", "unit_price_usd": "1", "total_price_usd": "1"}
        self.assertEqual(self.post("/api/kirim/", both).status_code, 400)
        self.assertEqual(self.post("/api/kirim/", {"material_id": self.mdf.pk, "quantity": "1"}).status_code, 400)

    def test_dashboard(self):
        self.client.force_login(self.admin)
        data = self.client.get("/api/dashboard/").json()
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["valuation_usd"], "437.20")
        self.assertEqual(data["current_month"]["kirim_usd"], "437.20")
        self.assertEqual(len(data["months"]), 6)
        self.assertEqual([row["material"]["name"] for row in data["low_stock"]], ["MDF 16 mm"])

        self.client.force_login(self.arrachi)
        self.assertEqual(self.client.get("/api/dashboard/").status_code, 403)

    def test_material_catalogue_is_admin_only_and_never_deletes(self):
        self.client.force_login(self.arrachi)
        self.assertEqual(self.client.get("/api/materials/").status_code, 403)

        self.client.force_login(self.admin)
        response = self.post("/api/materials/", {"name": "Lenta", "category": MaterialCategory.LINEAR, "unit_of_measure": MeasurementUnit.METER})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["allowed_roles"], [UserRole.SHKURKACHI, UserRole.SBORKACHI])
        self.assertEqual(self.client.delete(f"/api/materials/{self.mdf.pk}/").status_code, 405)


class LedgerApiTests(ApiTestCase):
    def test_workers_see_only_their_own_entries(self):
        services.withdraw_whole_material(material=self.paint, user=self.kraskachi, quantity=1)
        self.client.force_login(self.kraskachi)
        rows = self.client.get("/api/transactions/").json()["results"]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("unit_price_usd", rows[0])

    def test_admin_sees_and_filters_everything(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/transactions/").json()["count"], 3)
        self.assertEqual(self.client.get("/api/transactions/", {"type": "KIRIM"}).json()["count"], 2)
        self.assertEqual(self.client.get("/api/transactions/", {"user": self.arrachi.pk}).json()["count"], 1)
        self.assertEqual(self.client.get("/api/transactions/", {"category": "LIQUID"}).json()["count"], 1)
        self.assertEqual(self.client.get("/api/transactions/", {"month": "1999-01"}).json()["count"], 0)

    def test_the_ledger_is_read_only(self):
        self.client.force_login(self.admin)
        entry = InventoryTransaction.objects.first()
        self.assertEqual(self.client.delete(f"/api/transactions/{entry.pk}/").status_code, 405)
        self.assertEqual(self.client.put(f"/api/transactions/{entry.pk}/", {}, content_type="application/json").status_code, 405)
        self.assertEqual(self.post("/api/transactions/", {}).status_code, 405)
