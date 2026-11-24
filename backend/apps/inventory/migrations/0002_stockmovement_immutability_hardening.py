# Generated manually for StockMovement DB-level immutability hardening (trigger + PROTECT)

import django.db.models.deletion
from django.db import migrations, models

CREATE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION inventory_prevent_stockmovement_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'StockMovement ledger is strictly immutable (% forbidden)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS inventory_stockmovement_immutable_trigger ON inventory_stockmovement;
CREATE TRIGGER inventory_stockmovement_immutable_trigger
BEFORE UPDATE OR DELETE ON inventory_stockmovement
FOR EACH ROW
EXECUTE FUNCTION inventory_prevent_stockmovement_mutation();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS inventory_stockmovement_immutable_trigger ON inventory_stockmovement;
DROP FUNCTION IF EXISTS inventory_prevent_stockmovement_mutation();
"""


def add_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_TRIGGER_SQL, params=None)


def remove_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_TRIGGER_SQL, params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stockmovement",
            name="depot",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="depots.depot",
            ),
        ),
        migrations.RunPython(add_immutability_trigger, remove_immutability_trigger),
    ]
