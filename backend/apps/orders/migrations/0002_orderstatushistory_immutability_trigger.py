# PostgreSQL trigger enforcing strict DB-level immutability on OrderStatusHistory

from django.db import migrations

CREATE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION orders_prevent_status_history_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'OrderStatusHistory ledger is strictly immutable (% forbidden)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS orders_status_history_immutable_trigger ON orders_orderstatushistory;
CREATE TRIGGER orders_status_history_immutable_trigger
BEFORE UPDATE OR DELETE ON orders_orderstatushistory
FOR EACH ROW
EXECUTE FUNCTION orders_prevent_status_history_mutation();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS orders_status_history_immutable_trigger ON orders_orderstatushistory;
DROP FUNCTION IF EXISTS orders_prevent_status_history_mutation();
"""


def add_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_TRIGGER_SQL, params=None)


def remove_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_TRIGGER_SQL, params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_immutability_trigger, remove_immutability_trigger),
    ]
