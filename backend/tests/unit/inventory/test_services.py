"""Lot 2 (Jalon 2) : services de stock atomiques (restock / adjust / scrap) et statut éditable.

Tests boîte noire orientés spécification. Les tests « DURCISSEMENT » vont au-delà du texte
(débordements d'entiers, source de vérité du statut, valeur 0 falsy) : un échec est un FINDING.
Les tests d'atomicité patchent `StockMovement.save` : si le service insère ses mouvements
par `bulk_create`, ces deux tests sont à adapter.
"""
import random
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from apps.catalog.models import ProductStatus
from apps.core.exceptions import (
    ConflictDomainError,
    DomainError,
    ForbiddenDomainError,
    ValidationDomainError,
)
from apps.depots.models import Depot, DepotStatus
from apps.inventory import services
from apps.inventory.models import DepotStock, StockCategory, StockMovement, StockMovementType
from tests.constants import CODE_VALIDATION
from tests.domain_asserts import assert_domain_error
from tests.factories import utc
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot
from tests.factories_inventory import make_stock

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

CODE_NOT_EDITABLE = "DEPOT_NOT_EDITABLE"
CODE_STOCK_CONFLICT = "STOCK_CONFLICT"
CODE_BELOW_RESERVED = "STOCK_BELOW_RESERVED"
CODE_UNCHANGED = "STOCK_UNCHANGED"
CODE_INSUFFICIENT = "INSUFFICIENT_STOCK_FOR_SCRAP"

FULL, EMPTY, NEW, DEPOSIT = (StockCategory.FULL, StockCategory.EMPTY, StockCategory.NEW, StockCategory.DEPOSIT)
ALL_CATEGORIES = [FULL, EMPTY, NEW, DEPOSIT]
T = StockMovementType

BAD_QUANTITIES = [0, -1, -100, True, False, 1.5, "5", None]
BAD_QUANTITY_IDS = ["zero", "moins1", "moins100", "True", "False", "float", "str", "None"]
BAD_REASONS = ["", "   ", "\n\t "]
NOT_EDITABLE = [DepotStatus.SUSPENDED, DepotStatus.DISABLED]
EDITABLE = [DepotStatus.PENDING, DepotStatus.ACTIVE]
NOW = utc(2026, 3, 4, 12)


@pytest.fixture
def ctx():
    depot = make_depot()
    return SimpleNamespace(depot=depot, product=make_product(), actor=depot.manager)


def restock(c, quantity=5, category=FULL, **kw):
    return services.restock_depot_stock(
        depot=kw.pop("depot", c.depot), product=kw.pop("product", c.product),
        category=category, quantity=quantity, actor=c.actor, **kw)


def adjust(c, new, category=FULL, reason="Inventaire", **kw):
    return services.adjust_depot_stock(
        depot=kw.pop("depot", c.depot), product=kw.pop("product", c.product),
        category=category, new_physical_quantity=new, actor=c.actor, reason=reason, **kw)


def scrap(c, quantity, category=FULL, reason="Casse", **kw):
    return services.scrap_depot_stock(
        depot=kw.pop("depot", c.depot), product=kw.pop("product", c.product),
        category=category, quantity=quantity, actor=c.actor, reason=reason, **kw)


def stock_row(c, category=FULL):
    return DepotStock.objects.get(depot=c.depot, product=c.product, category=category)


def lines(c, category=None):
    qs = DepotStock.objects.filter(depot=c.depot, product=c.product)
    return qs.filter(category=category) if category else qs


def moves(c):
    return StockMovement.objects.filter(depot=c.depot, product=c.product)


def totals():
    return DepotStock.objects.count(), StockMovement.objects.count()


def details_of(excinfo):
    return excinfo.value.details


# ==========================================================================
# assert_depot_editable
# ==========================================================================
class TestAssertDepotEditable:
    @pytest.mark.parametrize("status", EDITABLE)
    def test_pending_and_active_depots_are_editable(self, status):
        assert services.assert_depot_editable(make_depot(status=status)) is None

    @pytest.mark.parametrize("status", NOT_EDITABLE)
    def test_suspended_and_disabled_depots_are_refused(self, status):
        with pytest.raises(ForbiddenDomainError) as exc:
            services.assert_depot_editable(make_depot(status=status))
        assert_domain_error(exc, ForbiddenDomainError, CODE_NOT_EDITABLE)

    def test_status_change_is_followed(self):
        depot = make_depot(status=DepotStatus.ACTIVE)
        services.assert_depot_editable(depot)
        depot.status = DepotStatus.SUSPENDED
        depot.save()  # mémoire ET base : valable que la fonction lise l'instance ou la base
        with pytest.raises(ForbiddenDomainError):
            services.assert_depot_editable(depot)
        depot.status = DepotStatus.ACTIVE
        depot.save()
        services.assert_depot_editable(depot)


# ==========================================================================
# restock_depot_stock
# ==========================================================================
class TestRestockNominal:
    def test_creates_the_line_when_absent_starting_from_zero(self, ctx):
        stock, movement = restock(ctx, 7)
        assert (stock.physical_quantity, stock.reserved_quantity) == (7, 0)
        assert (movement.quantity_before, movement.quantity_after, movement.delta) == (0, 7, 7)
        assert lines(ctx).count() == 1 and moves(ctx).count() == 1

    def test_increments_an_existing_line_without_touching_reservations(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, category=FULL, physical_quantity=10, reserved_quantity=3)
        stock, movement = restock(ctx, 5)
        row = stock_row(ctx)
        assert (row.physical_quantity, row.reserved_quantity) == (15, 3)
        assert (stock.physical_quantity, stock.reserved_quantity) == (15, 3)
        assert (movement.quantity_before, movement.quantity_after, movement.delta) == (10, 15, 5)

    def test_returns_a_persisted_stock_and_movement(self, ctx):
        stock, movement = restock(ctx, 3)
        assert isinstance(stock, DepotStock) and isinstance(movement, StockMovement)
        assert DepotStock.objects.filter(pk=stock.pk).exists() and StockMovement.objects.filter(pk=movement.pk).exists()

    def test_movement_records_type_actor_and_scope(self, ctx):
        _, movement = restock(ctx, 4, category=NEW)
        m = StockMovement.objects.get(pk=movement.pk)
        assert m.movement_type == T.RESTOCK
        assert (m.actor_id, m.depot_id, m.product_id, m.category) == (ctx.actor.pk, ctx.depot.pk, ctx.product.pk, NEW)

    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    def test_every_category_can_be_restocked(self, ctx, category):
        restock(ctx, 6, category=category)
        row = stock_row(ctx, category)
        assert (row.physical_quantity, row.reserved_quantity) == (6, 0)

    def test_categories_are_independent_lines(self, ctx):
        restock(ctx, 6, category=FULL)
        restock(ctx, 9, category=EMPTY)
        assert (stock_row(ctx, FULL).physical_quantity, stock_row(ctx, EMPTY).physical_quantity) == (6, 9)

    @pytest.mark.parametrize("raw,expected", [("  casse  ", "casse"), ("\nlivraison\t", "livraison"), ("   ", ""), ("", "")])
    def test_reason_is_stripped(self, ctx, raw, expected):
        _, movement = restock(ctx, 2, reason=raw)
        assert StockMovement.objects.get(pk=movement.pk).reason == expected

    def test_reason_defaults_to_empty(self, ctx):
        _, movement = restock(ctx, 2)
        assert StockMovement.objects.get(pk=movement.pk).reason == ""

    def test_successive_restocks_form_a_continuous_chain(self, ctx):
        _, first = restock(ctx, 4)
        _, second = restock(ctx, 6)
        assert second.quantity_before == first.quantity_after == 4 and second.quantity_after == 10

    def test_updated_at_moves_so_public_availability_timestamp_is_fresh(self, ctx):
        with freeze_time("2026-03-04 10:00:00"):
            restock(ctx, 1)
        with freeze_time("2026-03-04 11:30:00"):
            restock(ctx, 1)
        assert stock_row(ctx).updated_at == utc(2026, 3, 4, 11, 30)

    def test_other_depots_and_products_are_untouched(self, ctx):
        other_depot_stock = make_stock(product=ctx.product, physical_quantity=8)
        other_product_stock = make_stock(depot=ctx.depot, physical_quantity=8)
        restock(ctx, 5)
        assert DepotStock.objects.get(pk=other_depot_stock.pk).physical_quantity == 8
        assert DepotStock.objects.get(pk=other_product_stock.pk).physical_quantity == 8

    def test_arguments_are_keyword_only(self, ctx):
        with pytest.raises(TypeError):
            services.restock_depot_stock(ctx.depot, ctx.product, FULL, 5, ctx.actor)

    @pytest.mark.parametrize("status", EDITABLE)
    def test_editable_statuses_are_accepted(self, ctx, status):
        depot = make_depot(status=status)
        stock, _ = restock(ctx, 2, depot=depot)
        assert stock.physical_quantity == 2


class TestRestockValidation:
    @pytest.mark.parametrize("bad", BAD_QUANTITIES, ids=BAD_QUANTITY_IDS)
    def test_invalid_quantity_is_rejected_without_side_effect(self, ctx, bad):
        before = totals()
        with pytest.raises(ValidationDomainError) as exc:
            restock(ctx, bad)
        assert_domain_error(exc, ValidationDomainError, CODE_VALIDATION)
        assert totals() == before

    @pytest.mark.parametrize("bad", ["XX", "full", "", None])
    def test_invalid_category_is_rejected(self, ctx, bad):
        before = totals()
        with pytest.raises(ValidationDomainError):
            restock(ctx, 3, category=bad)
        assert totals() == before

    @pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.ARCHIVED])
    def test_unpublished_product_is_rejected(self, ctx, status):
        product = make_product(status=status)
        before = totals()
        with pytest.raises(ValidationDomainError) as exc:
            restock(ctx, 3, product=product)
        assert_domain_error(exc, ValidationDomainError, CODE_VALIDATION)
        assert totals() == before

    def test_product_of_an_inactive_brand_is_rejected(self, ctx):
        product = make_product(brand=make_brand(is_active=False))
        before = totals()
        with pytest.raises(ValidationDomainError):
            restock(ctx, 3, product=product)
        assert totals() == before

    @pytest.mark.parametrize("status", NOT_EDITABLE)
    def test_not_editable_depot_is_refused_without_side_effect(self, ctx, status):
        depot = make_depot(status=status)
        before = totals()
        with pytest.raises(ForbiddenDomainError) as exc:
            restock(ctx, 3, depot=depot)
        assert_domain_error(exc, ForbiddenDomainError, CODE_NOT_EDITABLE)
        assert totals() == before

    def test_status_is_re_read_from_the_database_stale_active_instance(self, ctx):
        """Instance en mémoire ACTIVE, base SUSPENDED : la base fait foi."""
        Depot.objects.filter(pk=ctx.depot.pk).update(status=DepotStatus.SUSPENDED)
        assert ctx.depot.status == DepotStatus.ACTIVE
        before = totals()
        with pytest.raises(ForbiddenDomainError) as exc:
            restock(ctx, 3)
        assert_domain_error(exc, ForbiddenDomainError, CODE_NOT_EDITABLE)
        assert totals() == before

    def test_database_is_the_source_of_truth_stale_suspended_instance(self, ctx):
        """DURCISSEMENT : instance en mémoire SUSPENDED mais base ACTIVE -> la mutation est permise."""
        ctx.depot.status = DepotStatus.SUSPENDED  # non sauvegardé
        stock, _ = restock(ctx, 3)
        assert stock.physical_quantity == 3

    @pytest.mark.parametrize("quantity", [2**31, 2**63, 10**30], ids=["2^31", "2^63", "1e30"])
    def test_overflowing_quantity_is_a_domain_error_or_stored_exactly(self, ctx, quantity):
        """DURCISSEMENT : jamais une DataError PostgreSQL brute (500)."""
        try:
            stock, _ = restock(ctx, quantity)
        except (ValidationDomainError, ConflictDomainError):
            assert totals() == (0, 0)
            return
        assert DepotStock.objects.get(pk=stock.pk).physical_quantity == quantity

    def test_cumulative_overflow_is_a_domain_error_or_stored_exactly(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, category=FULL, physical_quantity=2_147_483_000)
        try:
            restock(ctx, 1000)
        except (ValidationDomainError, ConflictDomainError):
            assert stock_row(ctx).physical_quantity == 2_147_483_000
            return
        assert stock_row(ctx).physical_quantity == 2_147_484_000


class TestRestockAtomicity:
    def test_movement_failure_rolls_back_an_existing_line(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, category=FULL, physical_quantity=10)
        with patch.object(StockMovement, "save", side_effect=RuntimeError("journal indisponible")):
            with pytest.raises(Exception):
                restock(ctx, 5)
        assert stock_row(ctx).physical_quantity == 10 and moves(ctx).count() == 0

    def test_movement_failure_does_not_leave_a_new_line_behind(self, ctx):
        with patch.object(StockMovement, "save", side_effect=RuntimeError("journal indisponible")):
            with pytest.raises(Exception):
                restock(ctx, 5)
        assert totals() == (0, 0)


# ==========================================================================
# adjust_depot_stock
# ==========================================================================
class TestAdjustNominal:
    def test_upward_adjustment(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10, reserved_quantity=2)
        stock, movement = adjust(ctx, 15)
        assert (stock_row(ctx).physical_quantity, stock_row(ctx).reserved_quantity) == (15, 2)
        assert (movement.quantity_before, movement.quantity_after, movement.delta) == (10, 15, 5)
        assert movement.movement_type == T.INVENTORY_CORRECTION

    def test_downward_adjustment(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10, reserved_quantity=3)
        _, movement = adjust(ctx, 4)
        assert stock_row(ctx).physical_quantity == 4
        assert (movement.quantity_before, movement.quantity_after, movement.delta) == (10, 4, -6)

    def test_adjusting_down_to_exactly_the_reserved_quantity_is_allowed(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10, reserved_quantity=3)
        adjust(ctx, 3)
        assert stock_row(ctx).physical_quantity == 3

    def test_adjusting_down_to_zero_without_reservation_is_allowed(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10, reserved_quantity=0)
        _, movement = adjust(ctx, 0)
        assert stock_row(ctx).physical_quantity == 0 and movement.delta == -10

    def test_manual_adjustment_type_is_accepted(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10)
        _, movement = adjust(ctx, 12, movement_type=T.MANUAL_ADJUSTMENT)
        assert StockMovement.objects.get(pk=movement.pk).movement_type == T.MANUAL_ADJUSTMENT

    def test_absent_line_is_created_from_zero(self, ctx):
        _, movement = adjust(ctx, 10, expected_physical_quantity=0)
        assert (movement.quantity_before, movement.quantity_after, movement.delta) == (0, 10, 10)
        assert stock_row(ctx).physical_quantity == 10

    def test_reason_is_stripped_and_actor_recorded(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=5)
        _, movement = adjust(ctx, 6, reason="  recomptage  ")
        m = StockMovement.objects.get(pk=movement.pk)
        assert (m.reason, m.actor_id) == ("recomptage", ctx.actor.pk)

    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    def test_every_category_can_be_adjusted(self, ctx, category):
        make_stock(depot=ctx.depot, product=ctx.product, category=category, physical_quantity=5)
        adjust(ctx, 8, category=category)
        assert stock_row(ctx, category).physical_quantity == 8

    def test_matching_expected_quantity_is_accepted(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10)
        adjust(ctx, 12, expected_physical_quantity=10)
        assert stock_row(ctx).physical_quantity == 12

    def test_updated_at_moves(self, ctx):
        with freeze_time("2026-03-04 10:00:00"):
            make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=5)
        with freeze_time("2026-03-04 11:30:00"):
            adjust(ctx, 6)
        assert stock_row(ctx).updated_at == utc(2026, 3, 4, 11, 30)

    def test_arguments_are_keyword_only(self, ctx):
        with pytest.raises(TypeError):
            services.adjust_depot_stock(ctx.depot, ctx.product, FULL, 5, ctx.actor, "raison")


class TestAdjustValidation:
    @pytest.fixture(autouse=True)
    def _stock(self, ctx):
        self.stock = make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10, reserved_quantity=3)

    def unchanged(self, ctx):
        row = stock_row(ctx)
        assert (row.physical_quantity, row.reserved_quantity) == (10, 3) and moves(ctx).count() == 0

    @pytest.mark.parametrize("movement_type", [t for t, _ in T.choices if t not in (T.INVENTORY_CORRECTION, T.MANUAL_ADJUSTMENT)])
    def test_only_two_movement_types_are_allowed(self, ctx, movement_type):
        with pytest.raises(ValidationDomainError):
            adjust(ctx, 12, movement_type=movement_type)
        self.unchanged(ctx)

    @pytest.mark.parametrize("bad", ["XX", "restock", "", None])
    def test_unknown_movement_type_is_rejected(self, ctx, bad):
        with pytest.raises(ValidationDomainError):
            adjust(ctx, 12, movement_type=bad)
        self.unchanged(ctx)

    @pytest.mark.parametrize("reason", BAD_REASONS + [None], ids=["vide", "espaces", "blancs", "None"])
    def test_reason_is_mandatory(self, ctx, reason):
        with pytest.raises(ValidationDomainError) as exc:
            adjust(ctx, 12, reason=reason)
        assert_domain_error(exc, ValidationDomainError, CODE_VALIDATION)
        self.unchanged(ctx)

    @pytest.mark.parametrize("bad", [-1, True, False, 1.5, "5", None], ids=["negatif", "True", "False", "float", "str", "None"])
    def test_new_quantity_must_be_a_non_negative_non_boolean_integer(self, ctx, bad):
        with pytest.raises(ValidationDomainError):
            adjust(ctx, bad)
        self.unchanged(ctx)

    def test_validation_takes_precedence_over_state_conflicts(self, ctx):
        """Raison vide ET quantité inchangée -> 400 (entrée invalide), pas 409."""
        with pytest.raises(ValidationDomainError):
            adjust(ctx, 10, reason="  ")

    @pytest.mark.parametrize("bad", ["XX", None])
    def test_invalid_category_is_rejected(self, ctx, bad):
        with pytest.raises(ValidationDomainError):
            adjust(ctx, 12, category=bad)

    @pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.ARCHIVED])
    def test_unpublished_product_is_rejected(self, ctx, status):
        with pytest.raises(ValidationDomainError):
            adjust(ctx, 5, product=make_product(status=status))

    @pytest.mark.parametrize("status", NOT_EDITABLE)
    def test_not_editable_depot_is_refused(self, ctx, status):
        with pytest.raises(ForbiddenDomainError) as exc:
            adjust(ctx, 5, depot=make_depot(status=status))
        assert_domain_error(exc, ForbiddenDomainError, CODE_NOT_EDITABLE)

    def test_status_is_re_read_from_the_database(self, ctx):
        Depot.objects.filter(pk=ctx.depot.pk).update(status=DepotStatus.DISABLED)
        with pytest.raises(ForbiddenDomainError) as exc:
            adjust(ctx, 12)
        assert_domain_error(exc, ForbiddenDomainError, CODE_NOT_EDITABLE)
        self.unchanged(ctx)

    def test_overflowing_new_quantity_is_a_domain_error_or_stored_exactly(self, ctx):
        try:
            adjust(ctx, 10**30)
        except DomainError:
            self.unchanged(ctx)
            return
        assert stock_row(ctx).physical_quantity == 10**30


class TestAdjustConflicts:
    @pytest.fixture(autouse=True)
    def _stock(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10, reserved_quantity=5)

    def unchanged(self, ctx):
        row = stock_row(ctx)
        assert (row.physical_quantity, row.reserved_quantity) == (10, 5) and moves(ctx).count() == 0

    def test_stale_expected_quantity_is_a_stock_conflict(self, ctx):
        with pytest.raises(ConflictDomainError) as exc:
            adjust(ctx, 12, expected_physical_quantity=8)
        assert_domain_error(exc, ConflictDomainError, CODE_STOCK_CONFLICT)
        assert details_of(exc)["current_physical_quantity"] == 10
        self.unchanged(ctx)

    def test_expected_zero_is_a_real_expectation_not_an_absent_one(self, ctx):
        """Piège `if expected:` : 0 est falsy et désactiverait l'optimistic locking."""
        with pytest.raises(ConflictDomainError) as exc:
            adjust(ctx, 12, expected_physical_quantity=0)
        assert_domain_error(exc, ConflictDomainError, CODE_STOCK_CONFLICT)
        assert details_of(exc)["current_physical_quantity"] == 10
        self.unchanged(ctx)

    @pytest.mark.parametrize("new", [4, 0])
    def test_below_reserved_is_refused(self, ctx, new):
        with pytest.raises(ConflictDomainError) as exc:
            adjust(ctx, new)
        assert_domain_error(exc, ConflictDomainError, CODE_BELOW_RESERVED)
        assert details_of(exc)["reserved_quantity"] == 5
        self.unchanged(ctx)

    def test_same_quantity_is_refused_as_unchanged(self, ctx):
        with pytest.raises(ConflictDomainError) as exc:
            adjust(ctx, 10)
        assert_domain_error(exc, ConflictDomainError, CODE_UNCHANGED)
        self.unchanged(ctx)

    def test_unchanged_on_an_absent_line_leaves_nothing_behind(self, ctx):
        other = make_product()
        with pytest.raises(ConflictDomainError) as exc:
            adjust(ctx, 0, product=other)
        assert_domain_error(exc, ConflictDomainError, CODE_UNCHANGED)
        assert not DepotStock.objects.filter(depot=ctx.depot, product=other).exists()
        assert not StockMovement.objects.filter(product=other).exists()

    def test_details_are_integers(self, ctx):
        with pytest.raises(ConflictDomainError) as exc:
            adjust(ctx, 12, expected_physical_quantity=8)
        assert isinstance(details_of(exc)["current_physical_quantity"], int)


class TestAdjustAtomicity:
    def test_movement_failure_rolls_the_adjustment_back(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10)
        with patch.object(StockMovement, "save", side_effect=RuntimeError("journal indisponible")):
            with pytest.raises(Exception):
                adjust(ctx, 15)
        assert stock_row(ctx).physical_quantity == 10 and moves(ctx).count() == 0


# ==========================================================================
# scrap_depot_stock
# ==========================================================================
class TestScrapNominal:
    @pytest.fixture(autouse=True)
    def _stock(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10, reserved_quantity=3)

    def test_scraps_and_records_a_negative_movement(self, ctx):
        stock, movement = scrap(ctx, 4)
        assert (stock_row(ctx).physical_quantity, stock_row(ctx).reserved_quantity) == (6, 3)
        assert (movement.quantity_before, movement.quantity_after, movement.delta) == (10, 6, -4)
        assert StockMovement.objects.get(pk=movement.pk).movement_type == T.SCRAP

    def test_scrapping_exactly_the_available_quantity_is_allowed(self, ctx):
        scrap(ctx, 7)
        row = stock_row(ctx)
        assert (row.physical_quantity, row.reserved_quantity) == (3, 3)

    def test_scrapping_everything_without_reservation(self, ctx):
        other = make_product()
        make_stock(depot=ctx.depot, product=other, physical_quantity=10, reserved_quantity=0)
        _, movement = scrap(ctx, 10, product=other)
        assert DepotStock.objects.get(depot=ctx.depot, product=other, category=FULL).physical_quantity == 0
        assert movement.delta == -10

    def test_reason_is_stripped_and_actor_recorded(self, ctx):
        _, movement = scrap(ctx, 1, reason="  bouteille fendue ")
        m = StockMovement.objects.get(pk=movement.pk)
        assert (m.reason, m.actor_id) == ("bouteille fendue", ctx.actor.pk)

    @pytest.mark.parametrize("category", [EMPTY, NEW, DEPOSIT])
    def test_other_categories_can_be_scrapped(self, ctx, category):
        make_stock(depot=ctx.depot, product=ctx.product, category=category, physical_quantity=5)
        scrap(ctx, 2, category=category)
        assert stock_row(ctx, category).physical_quantity == 3

    def test_updated_at_moves(self, ctx):
        with freeze_time("2026-03-04 11:30:00"):
            scrap(ctx, 1)
        assert stock_row(ctx).updated_at == utc(2026, 3, 4, 11, 30)

    def test_arguments_are_keyword_only(self, ctx):
        with pytest.raises(TypeError):
            services.scrap_depot_stock(ctx.depot, ctx.product, FULL, 1, ctx.actor, "raison")


class TestScrapRefusals:
    @pytest.fixture(autouse=True)
    def _stock(self, ctx):
        make_stock(depot=ctx.depot, product=ctx.product, physical_quantity=10, reserved_quantity=3)

    def unchanged(self, ctx):
        row = stock_row(ctx)
        assert (row.physical_quantity, row.reserved_quantity) == (10, 3) and moves(ctx).count() == 0

    @pytest.mark.parametrize("bad", BAD_QUANTITIES, ids=BAD_QUANTITY_IDS)
    def test_invalid_quantity_is_rejected(self, ctx, bad):
        with pytest.raises(ValidationDomainError) as exc:
            scrap(ctx, bad)
        assert_domain_error(exc, ValidationDomainError, CODE_VALIDATION)
        self.unchanged(ctx)

    @pytest.mark.parametrize("reason", BAD_REASONS + [None], ids=["vide", "espaces", "blancs", "None"])
    def test_reason_is_mandatory(self, ctx, reason):
        with pytest.raises(ValidationDomainError):
            scrap(ctx, 1, reason=reason)
        self.unchanged(ctx)

    @pytest.mark.parametrize("quantity", [11, 8, 100], ids=["au_dela_du_physique", "sous_le_reserve", "enorme"])
    def test_insufficient_stock(self, ctx, quantity):
        with pytest.raises(ConflictDomainError) as exc:
            scrap(ctx, quantity)
        assert_domain_error(exc, ConflictDomainError, CODE_INSUFFICIENT)
        assert details_of(exc)["physical_quantity"] == 10 and details_of(exc)["reserved_quantity"] == 3
        self.unchanged(ctx)

    def test_overflowing_quantity_is_a_conflict_not_a_database_error(self, ctx):
        with pytest.raises((ConflictDomainError, ValidationDomainError)):
            scrap(ctx, 10**30)
        self.unchanged(ctx)

    def test_scrap_on_an_absent_line_is_insufficient_and_creates_nothing(self, ctx):
        other = make_product()
        with pytest.raises(ConflictDomainError) as exc:
            scrap(ctx, 1, product=other)
        assert_domain_error(exc, ConflictDomainError, CODE_INSUFFICIENT)
        assert details_of(exc)["physical_quantity"] == 0 and details_of(exc)["reserved_quantity"] == 0
        assert not DepotStock.objects.filter(depot=ctx.depot, product=other).exists()

    @pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.ARCHIVED])
    def test_unpublished_product_is_rejected(self, ctx, status):
        with pytest.raises(ValidationDomainError):
            scrap(ctx, 1, product=make_product(status=status))

    @pytest.mark.parametrize("status", NOT_EDITABLE)
    def test_not_editable_depot_is_refused(self, ctx, status):
        with pytest.raises(ForbiddenDomainError) as exc:
            scrap(ctx, 1, depot=make_depot(status=status))
        assert_domain_error(exc, ForbiddenDomainError, CODE_NOT_EDITABLE)

    def test_status_is_re_read_from_the_database(self, ctx):
        Depot.objects.filter(pk=ctx.depot.pk).update(status=DepotStatus.SUSPENDED)
        with pytest.raises(ForbiddenDomainError) as exc:
            scrap(ctx, 1)
        assert_domain_error(exc, ForbiddenDomainError, CODE_NOT_EDITABLE)
        self.unchanged(ctx)

    def test_movement_failure_rolls_the_scrap_back(self, ctx):
        with patch.object(StockMovement, "save", side_effect=RuntimeError("journal indisponible")):
            with pytest.raises(Exception):
                scrap(ctx, 2)
        self.unchanged(ctx)


# ==========================================================================
# Cohérence entre services : modèle de référence
# ==========================================================================
class TestServicesConsistency:
    def test_movement_chain_is_continuous_across_services(self, ctx):
        steps = [("restock", 10), ("adjust", 25), ("scrap", 5), ("restock", 3), ("adjust", 7), ("scrap", 2)]
        results = []
        for kind, value in steps:
            fn = {"restock": restock, "adjust": adjust, "scrap": scrap}[kind]
            results.append(fn(ctx, value)[1])
        for previous, current in zip(results, results[1:]):
            assert current.quantity_before == previous.quantity_after
        assert stock_row(ctx).physical_quantity == results[-1].quantity_after
        assert sum(m.delta for m in results) == stock_row(ctx).physical_quantity

    def test_random_operation_sequence_matches_a_reference_model(self, ctx):
        rng = random.Random(20260304)
        make_stock(depot=ctx.depot, product=ctx.product, category=FULL, physical_quantity=20, reserved_quantity=3)
        physical, reserved = 20, 3
        expected = Counter()
        for _ in range(80):
            kind = rng.choice(["restock", "adjust", "scrap"])
            if kind == "restock":
                q = rng.randint(1, 8)
                restock(ctx, q)
                expected[(physical, physical + q, q, T.RESTOCK)] += 1
                physical += q
            elif kind == "adjust":
                new = rng.randint(0, 30)
                if new == physical:
                    with pytest.raises(ConflictDomainError) as exc:
                        adjust(ctx, new)
                    assert_domain_error(exc, ConflictDomainError, CODE_UNCHANGED)
                elif new < reserved:
                    with pytest.raises(ConflictDomainError) as exc:
                        adjust(ctx, new)
                    assert_domain_error(exc, ConflictDomainError, CODE_BELOW_RESERVED)
                else:
                    adjust(ctx, new)
                    expected[(physical, new, new - physical, T.INVENTORY_CORRECTION)] += 1
                    physical = new
            else:
                q = rng.randint(1, 12)
                if physical - q < 0 or physical - q < reserved:
                    with pytest.raises(ConflictDomainError) as exc:
                        scrap(ctx, q)
                    assert_domain_error(exc, ConflictDomainError, CODE_INSUFFICIENT)
                else:
                    scrap(ctx, q)
                    expected[(physical, physical - q, -q, T.SCRAP)] += 1
                    physical -= q
        row = stock_row(ctx)
        assert (row.physical_quantity, row.reserved_quantity) == (physical, reserved)
        actual = Counter((m.quantity_before, m.quantity_after, m.delta, m.movement_type) for m in moves(ctx))
        assert actual == expected, "journal différent du modèle de référence (mouvement manquant, doublé ou orphelin)"
        assert sum(m.delta for m in moves(ctx)) == physical - 20
