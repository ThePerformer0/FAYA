"""Lot 1 (Jalon 2) : DepotStock, StockMovement, contraintes SQL et immuabilité du journal.

Tests boîte noire orientés spécification. Les classes marquées « DURCISSEMENT » vérifient
des garanties plus fortes que la spécification écrite (contournements de l'immuabilité
Python) : un échec est un FINDING à examiner, pas une erreur de test.

Pattern SQL : `pytest.raises` à l'extérieur, `transaction.atomic()` à l'intérieur.
"""
import uuid
from decimal import Decimal  # noqa: F401  (réservé aux lots suivants)

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import ProtectedError
from freezegun import freeze_time

from apps.accounts.models import UserRole
from apps.inventory.models import DepotStock, StockCategory, StockMovement, StockMovementType
from tests.factories import utc
from tests.factories_catalog import make_product
from tests.factories_depots import make_depot
from tests.factories_inventory import make_movement, make_stock
from tests.helpers import create_user

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

STOCK_TABLE = DepotStock._meta.db_table
MOVEMENT_TABLE = StockMovement._meta.db_table

FULL, EMPTY, NEW, DEPOSIT = (
    StockCategory.FULL, StockCategory.EMPTY, StockCategory.NEW, StockCategory.DEPOSIT)
NON_EMPTY_CATEGORIES = [FULL, NEW, DEPOSIT]


def errors_of(obj):
    try:
        obj.full_clean()
    except ValidationError as exc:
        return exc.message_dict
    return {}


def unsaved_stock(**overrides):
    data = dict(depot=make_depot(), product=make_product(), category=FULL,
                physical_quantity=10, reserved_quantity=0)
    data.update(overrides)
    return DepotStock(**data)


def unsaved_movement(**overrides):
    data = dict(depot=make_depot(), product=make_product(), category=FULL,
                movement_type=StockMovementType.RESTOCK, quantity_before=0, quantity_after=5, delta=5)
    data.update(overrides)
    return StockMovement(**data)


def immediate_constraints(cursor):
    """Les FK Django sont DEFERRABLE INITIALLY DEFERRED : on force la vérification immédiate."""
    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def reload_movement(movement):
    return StockMovement.objects.get(pk=movement.pk)


# ==========================================================================
# Enums (niveau module)
# ==========================================================================
class TestEnums:
    def test_stock_categories(self):
        assert {v for v, _ in StockCategory.choices} == {"FULL", "EMPTY", "NEW", "DEPOSIT"}

    def test_movement_types(self):
        assert {v for v, _ in StockMovementType.choices} == {
            "RESTOCK", "MANUAL_ADJUSTMENT", "INVENTORY_CORRECTION", "SCRAP",
            "RESERVATION", "RELEASE", "PICKUP_OUT", "EMPTY_RETURN"}

    def test_enums_are_module_level_not_nested_on_models(self):
        from apps.inventory import models as inventory_models

        assert inventory_models.StockCategory is StockCategory
        assert inventory_models.StockMovementType is StockMovementType


# ==========================================================================
# DepotStock : identité, valeurs par défaut, horodatage
# ==========================================================================
class TestDepotStockBasics:
    def test_in_memory_defaults(self):
        stock = DepotStock()
        assert stock.physical_quantity == 0
        assert stock.reserved_quantity == 0

    def test_persisted_defaults(self):
        stock = DepotStock.objects.create(depot=make_depot(), product=make_product(), category=FULL)
        stock = DepotStock.objects.get(pk=stock.pk)
        assert (stock.physical_quantity, stock.reserved_quantity) == (0, 0)

    def test_pk_is_a_uuid_and_str_is_not_empty(self):
        stock = make_stock()
        assert isinstance(stock.pk, uuid.UUID)
        assert str(stock).strip() != ""

    def test_timestamps_are_timezone_aware(self):
        stock = make_stock()
        assert stock.created_at.tzinfo is not None and stock.updated_at.tzinfo is not None

    def test_updated_at_moves_on_save_but_created_at_does_not(self):
        with freeze_time("2026-03-04 10:00:00") as frozen:
            stock = make_stock()
            created = stock.created_at
            frozen.move_to("2026-03-04 11:30:00")
            stock.physical_quantity = 20
            stock.save()
        stock.refresh_from_db()
        assert stock.created_at == created
        assert stock.updated_at > created

    @pytest.mark.parametrize("bad", ["full", "SOLD", "", "XX"])
    def test_unknown_category_is_rejected(self, bad):
        assert errors_of(unsaved_stock(category=bad))

    def test_product_is_protected_against_deletion(self):
        stock = make_stock()
        with pytest.raises(ProtectedError):
            stock.product.delete()
        assert DepotStock.objects.filter(pk=stock.pk).exists()

    def test_stock_quantities_round_trip_large_values(self):
        stock = make_stock(physical_quantity=2_000_000_000, reserved_quantity=1_999_999_999)
        stock = DepotStock.objects.get(pk=stock.pk)
        assert (stock.physical_quantity, stock.reserved_quantity) == (2_000_000_000, 1_999_999_999)


# ==========================================================================
# DepotStock.available_quantity
# ==========================================================================
AVAILABLE_CASES = [
    (FULL, 10, 3, 7),
    (FULL, 5, 5, 0),
    (FULL, 0, 0, 0),
    (FULL, 1, 0, 1),
    (NEW, 8, 2, 6),
    (DEPOSIT, 4, 1, 3),
    (EMPTY, 10, 0, 0),
    (EMPTY, 100, 0, 0),
    (EMPTY, 0, 0, 0),
    (FULL, 2_000_000_000, 1, 1_999_999_999),
]


class TestAvailableQuantity:
    @pytest.mark.parametrize("category,physical,reserved,expected", AVAILABLE_CASES)
    def test_available_quantity_table(self, category, physical, reserved, expected):
        stock = DepotStock(category=category, physical_quantity=physical, reserved_quantity=reserved)
        assert stock.available_quantity == expected

    def test_empty_bottles_are_never_sellable_even_in_an_inconsistent_state(self):
        stock = DepotStock(category=EMPTY, physical_quantity=50, reserved_quantity=7)
        assert stock.available_quantity == 0

    def test_property_returns_an_int(self):
        stock = DepotStock(category=FULL, physical_quantity=10, reserved_quantity=4)
        assert isinstance(stock.available_quantity, int) and not isinstance(stock.available_quantity, bool)

    def test_property_follows_in_memory_changes(self):
        stock = DepotStock(category=FULL, physical_quantity=10, reserved_quantity=4)
        stock.reserved_quantity = 10
        assert stock.available_quantity == 0
        stock.physical_quantity = 15
        assert stock.available_quantity == 5

    def test_persisted_instance_gives_the_same_result_without_any_query(self, django_assert_num_queries):
        stock = DepotStock.objects.get(pk=make_stock(physical_quantity=9, reserved_quantity=4).pk)
        with django_assert_num_queries(0):
            assert stock.available_quantity == 5

    def test_empty_category_loaded_from_the_database_is_always_zero(self):
        stock = DepotStock.objects.get(pk=make_stock(category=EMPTY, physical_quantity=30).pk)
        assert stock.available_quantity == 0


# ==========================================================================
# DepotStock : validation Django (full_clean / clean)
# ==========================================================================
class TestDepotStockValidation:
    def test_a_well_formed_stock_passes_full_clean(self):
        assert errors_of(unsaved_stock()) == {}

    @pytest.mark.parametrize("category", NON_EMPTY_CATEGORIES)
    def test_reserved_equal_to_physical_is_valid(self, category):
        assert errors_of(unsaved_stock(category=category, physical_quantity=5, reserved_quantity=5)) == {}

    def test_zero_zero_is_valid(self):
        assert errors_of(unsaved_stock(physical_quantity=0, reserved_quantity=0)) == {}

    def test_negative_physical_quantity_is_rejected(self):
        assert errors_of(unsaved_stock(physical_quantity=-1, reserved_quantity=0))

    def test_negative_reserved_quantity_is_rejected(self):
        assert errors_of(unsaved_stock(physical_quantity=5, reserved_quantity=-1))

    @pytest.mark.parametrize("field", ["physical_quantity", "reserved_quantity"])
    def test_null_quantities_are_rejected(self, field):
        assert errors_of(unsaved_stock(**{field: None}))

    @pytest.mark.parametrize("category", NON_EMPTY_CATEGORIES)
    def test_reserved_greater_than_physical_is_rejected(self, category):
        assert errors_of(unsaved_stock(category=category, physical_quantity=5, reserved_quantity=6))

    def test_empty_category_with_reservation_is_rejected(self):
        assert errors_of(unsaved_stock(category=EMPTY, physical_quantity=10, reserved_quantity=1))

    def test_empty_category_without_reservation_is_valid(self):
        assert errors_of(unsaved_stock(category=EMPTY, physical_quantity=10, reserved_quantity=0)) == {}

    @pytest.mark.parametrize("category", NON_EMPTY_CATEGORIES)
    def test_reservations_are_allowed_on_non_empty_categories(self, category):
        assert errors_of(unsaved_stock(category=category, physical_quantity=10, reserved_quantity=4)) == {}

    def test_duplicate_depot_product_category_is_caught_by_full_clean(self):
        stock = make_stock()
        duplicate = DepotStock(depot=stock.depot, product=stock.product, category=stock.category,
                               physical_quantity=1, reserved_quantity=0)
        assert errors_of(duplicate)

    def test_same_product_in_another_category_is_valid(self):
        stock = make_stock(category=FULL)
        other = DepotStock(depot=stock.depot, product=stock.product, category=EMPTY,
                           physical_quantity=1, reserved_quantity=0)
        assert errors_of(other) == {}


# ==========================================================================
# DepotStock : contraintes SQL (full_clean contourné)
# ==========================================================================
class TestDepotStockSqlConstraints:
    # --- unicité (depot, product, category) -------------------------------
    def test_unique_depot_product_category(self):
        stock = make_stock()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_stock(depot=stock.depot, product=stock.product, category=stock.category)

    def test_each_category_is_a_distinct_row_for_the_same_product(self):
        base = make_stock(category=FULL)
        for category in (EMPTY, NEW, DEPOSIT):
            make_stock(depot=base.depot, product=base.product, category=category, physical_quantity=1)
        assert DepotStock.objects.filter(depot=base.depot, product=base.product).count() == 4

    def test_same_product_and_category_in_another_depot_is_allowed(self):
        base = make_stock()
        make_stock(product=base.product, category=base.category)
        assert DepotStock.objects.filter(product=base.product).count() == 2

    def test_same_depot_and_category_for_another_product_is_allowed(self):
        base = make_stock()
        make_stock(depot=base.depot, category=base.category)
        assert DepotStock.objects.filter(depot=base.depot).count() == 2

    def test_bulk_create_cannot_bypass_uniqueness(self):
        depot, product = make_depot(), make_product()
        rows = [DepotStock(depot=depot, product=product, category=FULL, physical_quantity=1) for _ in range(2)]
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.bulk_create(rows)
        assert DepotStock.objects.count() == 0

    def test_update_into_a_duplicate_category_is_refused(self):
        base = make_stock(category=FULL)
        other = make_stock(depot=base.depot, product=base.product, category=NEW)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.filter(pk=other.pk).update(category=FULL)

    # --- physical_quantity >= 0 -------------------------------------------
    def test_negative_physical_is_refused_on_create(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_stock(physical_quantity=-1)

    def test_negative_physical_is_refused_on_update(self):
        stock = make_stock(physical_quantity=5)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.filter(pk=stock.pk).update(physical_quantity=-1)
        assert DepotStock.objects.get(pk=stock.pk).physical_quantity == 5

    def test_negative_physical_is_refused_via_raw_sql(self):
        stock = make_stock()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE "{STOCK_TABLE}" SET physical_quantity = -1 WHERE id = %s', [stock.pk])

    # --- reserved_quantity >= 0 -------------------------------------------
    def test_negative_reserved_is_refused_on_create(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_stock(physical_quantity=5, reserved_quantity=-1)

    def test_negative_reserved_is_refused_on_update(self):
        stock = make_stock(physical_quantity=5, reserved_quantity=1)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.filter(pk=stock.pk).update(reserved_quantity=-1)

    def test_negative_reserved_is_refused_via_raw_sql(self):
        stock = make_stock()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE "{STOCK_TABLE}" SET reserved_quantity = -1 WHERE id = %s', [stock.pk])

    # --- reserved <= physical ---------------------------------------------
    def test_reserved_above_physical_is_refused_on_create(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_stock(physical_quantity=5, reserved_quantity=6)

    def test_raising_reserved_above_physical_is_refused_on_update(self):
        stock = make_stock(physical_quantity=5, reserved_quantity=2)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.filter(pk=stock.pk).update(reserved_quantity=6)
        assert DepotStock.objects.get(pk=stock.pk).reserved_quantity == 2

    def test_lowering_physical_below_reserved_is_refused_on_update(self):
        stock = make_stock(physical_quantity=5, reserved_quantity=3)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.filter(pk=stock.pk).update(physical_quantity=2)
        assert DepotStock.objects.get(pk=stock.pk).physical_quantity == 5

    def test_reserved_above_physical_is_refused_via_raw_sql(self):
        stock = make_stock(physical_quantity=5, reserved_quantity=0)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f'UPDATE "{STOCK_TABLE}" SET reserved_quantity = physical_quantity + 1 WHERE id = %s',
                        [stock.pk])

    def test_reserved_equal_to_physical_is_accepted(self):
        stock = make_stock(physical_quantity=5, reserved_quantity=5)
        assert DepotStock.objects.get(pk=stock.pk).available_quantity == 0

    def test_a_simultaneous_decrease_of_both_values_keeping_the_rule_is_accepted(self):
        stock = make_stock(physical_quantity=10, reserved_quantity=8)
        DepotStock.objects.filter(pk=stock.pk).update(physical_quantity=4, reserved_quantity=3)
        assert DepotStock.objects.get(pk=stock.pk).physical_quantity == 4

    # --- EMPTY => reserved == 0 -------------------------------------------
    def test_empty_with_reservation_is_refused_on_create(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_stock(category=EMPTY, physical_quantity=5, reserved_quantity=1)

    def test_switching_a_reserved_row_to_empty_is_refused_on_update(self):
        stock = make_stock(category=FULL, physical_quantity=5, reserved_quantity=2)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.filter(pk=stock.pk).update(category=EMPTY)
        assert DepotStock.objects.get(pk=stock.pk).category == FULL

    def test_reserving_an_empty_row_is_refused_on_update(self):
        stock = make_stock(category=EMPTY, physical_quantity=10, reserved_quantity=0)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.filter(pk=stock.pk).update(reserved_quantity=1)

    def test_empty_with_reservation_is_refused_via_raw_sql(self):
        stock = make_stock(category=EMPTY, physical_quantity=10, reserved_quantity=0)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE "{STOCK_TABLE}" SET reserved_quantity = 1 WHERE id = %s', [stock.pk])

    def test_empty_without_reservation_is_accepted(self):
        stock = make_stock(category=EMPTY, physical_quantity=10, reserved_quantity=0)
        assert DepotStock.objects.get(pk=stock.pk).physical_quantity == 10

    @pytest.mark.parametrize("category", NON_EMPTY_CATEGORIES)
    def test_other_categories_can_hold_reservations(self, category):
        stock = make_stock(category=category, physical_quantity=10, reserved_quantity=4)
        assert DepotStock.objects.get(pk=stock.pk).reserved_quantity == 4

    # --- NOT NULL et clés étrangères --------------------------------------
    @pytest.mark.parametrize("field", ["physical_quantity", "reserved_quantity", "category", "depot", "product"])
    def test_required_columns_reject_null(self, field):
        stock = make_stock()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotStock.objects.filter(pk=stock.pk).update(**{field: None})

    def test_depot_foreign_key_is_enforced_by_the_database(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    immediate_constraints(cursor)
                DepotStock.objects.create(depot_id=uuid.uuid4(), product=make_product(), category=FULL)

    def test_product_foreign_key_is_enforced_by_the_database(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    immediate_constraints(cursor)
                DepotStock.objects.create(depot=make_depot(), product_id=uuid.uuid4(), category=FULL)

    def test_database_refuses_to_delete_a_product_that_has_stock(self):
        """PROTECT est une règle Python : on vérifie aussi la clé étrangère SQL."""
        stock = make_stock()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    immediate_constraints(cursor)
                    cursor.execute(f'DELETE FROM "{stock.product._meta.db_table}" WHERE id = %s', [stock.product_id])


# ==========================================================================
# StockMovement : création et validation
# ==========================================================================
class TestStockMovementBasics:
    def test_in_memory_defaults(self):
        assert StockMovement().reason == ""

    def test_creation_persists_every_field(self, admin_user):
        depot, product = make_depot(), make_product()
        movement = make_movement(depot=depot, product=product, category=NEW,
                                 movement_type=StockMovementType.SCRAP, quantity_before=10,
                                 delta=-3, reason="casse", actor=admin_user)
        m = reload_movement(movement)
        assert (m.depot_id, m.product_id, m.category, m.movement_type) == (
            depot.pk, product.pk, NEW, StockMovementType.SCRAP)
        assert (m.quantity_before, m.quantity_after, m.delta) == (10, 7, -3)
        assert (m.reason, m.actor_id) == ("casse", admin_user.pk)

    def test_pk_is_a_uuid_and_str_is_not_empty(self):
        m = make_movement()
        assert isinstance(m.pk, uuid.UUID) and str(m).strip() != ""

    def test_actor_is_optional(self):
        assert reload_movement(make_movement(actor=None)).actor_id is None

    def test_reason_defaults_to_empty_string(self):
        assert reload_movement(make_movement()).reason == ""

    def test_unicode_reason_round_trips(self):
        reason = "Bouteilles abîmées à l'entrepôt de Bonabéri 🔥"
        assert reload_movement(make_movement(reason=reason)).reason == reason

    @freeze_time("2026-03-04 10:00:00")
    def test_created_at_is_automatic_and_timezone_aware(self):
        m = reload_movement(make_movement())
        assert m.created_at == utc(2026, 3, 4, 10) and m.created_at.tzinfo is not None

    def test_created_at_cannot_be_backdated(self):
        m = reload_movement(make_movement(created_at=utc(2000, 1, 1)))
        assert m.created_at.year != 2000, "un mouvement ne doit pas pouvoir être antidaté"

    @pytest.mark.parametrize("movement_type", [t for t, _ in StockMovementType.choices])
    def test_every_movement_type_can_be_stored(self, movement_type):
        assert reload_movement(make_movement(movement_type=movement_type)).movement_type == movement_type

    @pytest.mark.parametrize("category", [c for c, _ in StockCategory.choices])
    def test_every_category_can_be_stored(self, category):
        assert reload_movement(make_movement(category=category)).category == category

    @pytest.mark.parametrize("bad", ["restock", "SOLD", "", "XX"])
    def test_unknown_movement_type_is_rejected(self, bad):
        assert errors_of(unsaved_movement(movement_type=bad))

    @pytest.mark.parametrize("bad", ["full", "SOLD", "", "XX"])
    def test_unknown_category_is_rejected(self, bad):
        assert errors_of(unsaved_movement(category=bad))

    def test_a_well_formed_movement_passes_full_clean(self):
        assert errors_of(unsaved_movement()) == {}

    def test_an_inconsistent_delta_is_caught_by_full_clean(self):
        assert errors_of(unsaved_movement(quantity_before=5, quantity_after=8, delta=4))


# ==========================================================================
# StockMovement : contraintes SQL
# ==========================================================================
class TestStockMovementSqlConstraints:
    def test_negative_quantity_before_is_refused(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_movement(quantity_before=-1, quantity_after=4, delta=5)

    def test_negative_quantity_after_is_refused(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_movement(quantity_before=2, quantity_after=-1, delta=-3)

    @pytest.mark.parametrize("before,after,delta", [(5, 8, 4), (5, 8, -3), (5, 8, 0), (10, 7, 3), (0, 0, 1)])
    def test_delta_must_equal_after_minus_before(self, before, after, delta):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_movement(quantity_before=before, quantity_after=after, delta=delta)

    @pytest.mark.parametrize("before,after,delta", [(0, 5, 5), (10, 7, -3), (4, 4, 0), (0, 0, 0)])
    def test_consistent_deltas_are_accepted(self, before, after, delta):
        m = make_movement(quantity_before=before, quantity_after=after, delta=delta)
        assert reload_movement(m).delta == delta

    def test_bulk_create_cannot_bypass_the_delta_rule(self):
        row = StockMovement(depot=make_depot(), product=make_product(), category=FULL,
                            movement_type=StockMovementType.RESTOCK, quantity_before=0, quantity_after=5, delta=9)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.bulk_create([row])

    @pytest.mark.parametrize("field", ["category", "movement_type", "quantity_before", "quantity_after", "delta",
                                       "depot", "product"])
    def test_required_columns_reject_null_on_insert(self, field):
        data = dict(depot=make_depot(), product=make_product(), category=FULL,
                    movement_type=StockMovementType.RESTOCK, quantity_before=0, quantity_after=5, delta=5)
        data[field] = None
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(**data)

    def test_depot_foreign_key_is_enforced_by_the_database(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    immediate_constraints(cursor)
                StockMovement.objects.create(
                    depot_id=uuid.uuid4(), product=make_product(), category=FULL,
                    movement_type=StockMovementType.RESTOCK, quantity_before=0, quantity_after=1, delta=1)


# ==========================================================================
# StockMovement : immuabilité (spécification : PermissionError)
# ==========================================================================
class TestStockMovementImmutability:
    def test_save_on_a_persisted_movement_raises_permission_error(self):
        m = make_movement(reason="initial")
        m.reason = "falsifié"
        with pytest.raises(PermissionError):
            m.save()
        assert reload_movement(m).reason == "initial"

    def test_save_without_any_change_is_also_refused(self):
        m = make_movement()
        with pytest.raises(PermissionError):
            m.save()

    def test_save_with_update_fields_is_refused(self):
        m = make_movement(reason="initial")
        m.reason = "falsifié"
        with pytest.raises(PermissionError):
            m.save(update_fields=["reason"])
        assert reload_movement(m).reason == "initial"

    def test_delete_on_an_instance_raises_permission_error(self):
        m = make_movement()
        with pytest.raises(PermissionError):
            m.delete()
        assert StockMovement.objects.filter(pk=m.pk).exists()

    def test_queryset_update_raises_permission_error(self):
        m = make_movement(reason="initial")
        with pytest.raises(PermissionError):
            StockMovement.objects.filter(pk=m.pk).update(reason="falsifié")
        assert reload_movement(m).reason == "initial"

    def test_queryset_update_of_amounts_raises_permission_error(self):
        m = make_movement(quantity_before=0, delta=5)
        with pytest.raises(PermissionError):
            StockMovement.objects.filter(pk=m.pk).update(quantity_after=0, delta=0)
        assert (reload_movement(m).quantity_after, reload_movement(m).delta) == (5, 5)

    def test_update_on_all_rows_raises_permission_error(self):
        m = make_movement(reason="initial")
        with pytest.raises(PermissionError):
            StockMovement.objects.all().update(reason="falsifié")
        assert reload_movement(m).reason == "initial"

    def test_queryset_delete_raises_permission_error(self):
        m = make_movement()
        with pytest.raises(PermissionError):
            StockMovement.objects.filter(pk=m.pk).delete()
        assert StockMovement.objects.filter(pk=m.pk).exists()

    def test_delete_on_all_rows_raises_permission_error(self):
        make_movement(), make_movement()
        with pytest.raises(PermissionError):
            StockMovement.objects.all().delete()
        assert StockMovement.objects.count() == 2

    def test_update_or_create_on_an_existing_movement_is_refused(self):
        m = make_movement(reason="initial")
        with pytest.raises(PermissionError):
            StockMovement.objects.update_or_create(pk=m.pk, defaults={"reason": "falsifié"})
        assert reload_movement(m).reason == "initial"

    def test_bulk_update_is_refused(self):
        m = make_movement(reason="initial")
        m.reason = "falsifié"
        with pytest.raises(PermissionError):
            StockMovement.objects.bulk_update([m], ["reason"])
        assert reload_movement(m).reason == "initial"

    def test_creating_new_movements_remains_possible_after_a_refusal(self):
        m = make_movement()
        with pytest.raises(PermissionError):
            m.delete()
        make_movement()
        assert StockMovement.objects.count() == 2

    def test_refusals_do_not_break_the_surrounding_transaction(self):
        m = make_movement()
        with pytest.raises(PermissionError):
            m.delete()
        assert StockMovement.objects.filter(pk=m.pk).exists()  # la connexion reste utilisable

    def test_a_successful_insert_does_not_raise(self):
        assert StockMovement.objects.count() == 0
        make_movement()
        assert StockMovement.objects.count() == 1


# ==========================================================================
# DURCISSEMENT : contournements de l'immuabilité Python
# ==========================================================================
class TestStockMovementImmutabilityBypasses:
    def test_new_instance_with_an_existing_pk_cannot_overwrite_history(self):
        """`StockMovement(pk=existant, ...).save()` fait un UPDATE : il doit être refusé."""
        m = make_movement(reason="initial", quantity_before=0, delta=5)
        clone = StockMovement(
            pk=m.pk, depot_id=m.depot_id, product_id=m.product_id, category=m.category,
            movement_type=m.movement_type, quantity_before=0, quantity_after=1, delta=1, reason="falsifié")
        try:
            with transaction.atomic():
                clone.save()
        except (PermissionError, IntegrityError):
            pass
        stored = reload_movement(m)
        assert (stored.reason, stored.quantity_after, stored.delta) == ("initial", 5, 5), "historique écrasé"

    def test_create_with_an_existing_pk_is_refused(self):
        m = make_movement(reason="initial")
        with pytest.raises((IntegrityError, PermissionError)):
            with transaction.atomic():
                StockMovement.objects.create(
                    pk=m.pk, depot_id=m.depot_id, product_id=m.product_id, category=m.category,
                    movement_type=m.movement_type, quantity_before=0, quantity_after=1, delta=1, reason="falsifié")
        assert reload_movement(m).reason == "initial"

    def test_bulk_create_upsert_cannot_overwrite_history(self):
        m = make_movement(reason="initial")
        clone = StockMovement(
            pk=m.pk, depot_id=m.depot_id, product_id=m.product_id, category=m.category,
            movement_type=m.movement_type, quantity_before=0, quantity_after=5, delta=5, reason="falsifié")
        try:
            with transaction.atomic():
                StockMovement.objects.bulk_create(
                    [clone], update_conflicts=True, unique_fields=["id"], update_fields=["reason"])
        except (PermissionError, IntegrityError, ValueError, NotImplementedError):
            pass
        assert reload_movement(m).reason == "initial", "bulk_create(update_conflicts=True) réécrit le journal"

    def test_raw_sql_update_is_refused_by_the_database(self):
        """Le journal « strictement immuable » devrait l'être aussi en base (trigger)."""
        m = make_movement(reason="initial")
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE "{MOVEMENT_TABLE}" SET reason = %s WHERE id = %s', ["falsifié", m.pk])
        except DatabaseError:
            return
        assert reload_movement(m).reason == "initial", "journal modifiable en SQL brut (pas de trigger d'immuabilité)"

    def test_raw_sql_delete_is_refused_by_the_database(self):
        m = make_movement()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'DELETE FROM "{MOVEMENT_TABLE}" WHERE id = %s', [m.pk])
        except DatabaseError:
            return
        assert StockMovement.objects.filter(pk=m.pk).exists(), "journal effaçable en SQL brut (pas de trigger)"

    def test_history_survives_deletion_of_its_actor(self):
        actor = create_user(role=UserRole.ADMIN, is_staff=True)
        m = make_movement(actor=actor)
        try:
            with transaction.atomic():
                actor.delete()
        except (ProtectedError, PermissionError, IntegrityError):
            pass  # refus explicite acceptable
        assert StockMovement.objects.filter(pk=m.pk).exists(), "supprimer l'acteur a détruit le journal"

    def test_history_survives_deletion_of_its_depot(self):
        depot = make_depot()
        m = make_movement(depot=depot)
        try:
            with transaction.atomic():
                depot.delete()
        except (ProtectedError, PermissionError, IntegrityError):
            pass
        assert StockMovement.objects.filter(pk=m.pk).exists(), (
            "supprimer le dépôt a détruit son journal (CASCADE contourne delete() et QuerySet.delete())")

    def test_history_survives_deletion_of_its_product(self):
        product = make_product()
        m = make_movement(product=product)
        try:
            with transaction.atomic():
                product.delete()
        except (ProtectedError, PermissionError, IntegrityError):
            pass
        assert StockMovement.objects.filter(pk=m.pk).exists(), "supprimer le produit a détruit le journal"
