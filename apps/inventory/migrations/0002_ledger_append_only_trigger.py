"""
Database-level guarantee that the inventory ledger is append-only.

On PostgreSQL a trigger rejects every UPDATE or DELETE on
``inventory_inventorytransaction``, so history cannot be rewritten even with
raw SQL or a buggy future code path. (The ORM-level guards in the model and
queryset stay in place for every backend.) Other backends are skipped.

If a future data migration must correct historical rows, it has to disable
the trigger explicitly, which makes such a change deliberate and reviewable.
"""

from django.db import migrations

CREATE_SQL = """
CREATE OR REPLACE FUNCTION inventory_ledger_reject_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'inventory_inventorytransaction is append-only (% rejected)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS inventory_ledger_append_only ON inventory_inventorytransaction;
CREATE TRIGGER inventory_ledger_append_only
    BEFORE UPDATE OR DELETE ON inventory_inventorytransaction
    FOR EACH ROW EXECUTE FUNCTION inventory_ledger_reject_change();
"""

DROP_SQL = """
DROP TRIGGER IF EXISTS inventory_ledger_append_only ON inventory_inventorytransaction;
DROP FUNCTION IF EXISTS inventory_ledger_reject_change();
"""


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_SQL, params=None)


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_SQL, params=None)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunPython(create_trigger, drop_trigger)]
