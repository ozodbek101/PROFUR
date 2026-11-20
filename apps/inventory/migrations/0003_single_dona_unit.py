# Merge the two "dona" units into one and use Uzbek unit names.
# "SHEET" (sheet count) and "PIECE" behaved identically (whole numbers, shown as "dona"),
# so existing SHEET materials become PIECE. Quantities and history are unchanged.

from django.db import migrations, models


def sheet_to_piece(apps, schema_editor):
    BaseMaterial = apps.get_model("inventory", "BaseMaterial")
    BaseMaterial.objects.filter(unit_of_measure="SHEET").update(unit_of_measure="PIECE")


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_ledger_append_only_trigger'),
    ]

    operations = [
        migrations.RunPython(sheet_to_piece, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='basematerial',
            name='unit_of_measure',
            field=models.CharField(choices=[('PIECE', 'Dona'), ('LITER', 'Litr'), ('KG', 'Kilogramm'), ('METER', 'Metr'), ('CM', 'Santimetr')], max_length=20, verbose_name="O'lchov birligi"),
        ),
    ]
