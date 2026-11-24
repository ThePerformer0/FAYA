"""Lot 2 (Jalon 2) : concurrence réelle PostgreSQL sur les services de stock.

Chaque scénario est rejoué plusieurs fois (`round_`) car une course n'apparaît pas à
chaque exécution. Chaque worker appelle `close_old_connections()` avant et après son travail
(en plus de `connections.close_all()` fait par `run_concurrently`).

Un échec ici est un vrai défaut de verrouillage : lost update, IntegrityError à la création
concurrente de ligne, stock négatif, mutation après suspension, mouvement orphelin.
"""
from collections import Counter
from functools import partial

import pytest
from django.db import close_old_connections

from apps.core.exceptions import ConflictDomainError, ForbiddenDomainError
from apps.core.models import AuditLog
from apps.depots.models import Depot, DepotStatus
from apps.depots.services import change_depot_status
from apps.inventory import services
from apps.inventory.models import DepotStock, StockCategory, StockMovement, StockMovementType
from tests.concurrency_helpers import run_concurrently, split
from tests.constants_j1 import AUDIT_DEPOT_SUSPENDED
from tests.domain_asserts import code_of
from tests.factories_catalog import make_product
from tests.factories_depots import make_depot
from tests.factories_inventory import make_stock

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]

THREADS = 10
ROUNDS = range(3)
FULL, EMPTY = StockCategory.FULL, StockCategory.EMPTY
T = StockMovementType

CODE_STOCK_CONFLICT = "STOCK_CONFLICT"
CODE_BELOW_RESERVED = "STOCK_BELOW_RESERVED"
CODE_UNCHANGED = "STOCK_UNCHANGED"
CODE_INSUFFICIENT = "INSUFFICIENT_STOCK_FOR_SCRAP"
CODE_NOT_EDITABLE = "DEPOT_NOT_EDITABLE"


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------
def job(fn, **kwargs):
    def run():
        close_old_connections()
        try:
            return fn(**kwargs)
        finally:
            close_old_connections()
    return run


def fresh(depot):
    return Depot.objects.get(pk=depot.pk)


def restock_job(depot, product, quantity, category=FULL):
    return job(services.restock_depot_stock, depot=fresh(depot), product=product, category=category,
               quantity=quantity, actor=depot.manager)


def scrap_job(depot, product, quantity, category=FULL):
    return job(services.scrap_depot_stock, depot=fresh(depot), product=product, category=category,
               quantity=quantity, actor=depot.manager, reason="Casse")


def adjust_job(depot, product, new, category=FULL, expected=None):
    kwargs = dict(depot=fresh(depot), product=product, category=category, new_physical_quantity=new,
                  actor=depot.manager, reason="Inventaire")
    if expected is not None:
        kwargs["expected_physical_quantity"] = expected
    return job(services.adjust_depot_stock, **kwargs)


def row(depot, product, category=FULL):
    return DepotStock.objects.get(depot=depot, product=product, category=category)


def movements(depot, product, category=FULL, **extra):
    return list(StockMovement.objects.filter(depot=depot, product=product, category=category, **extra)
                .order_by("created_at", "id"))


def assert_contiguous(ordered):
    """Chaîne (before, after) sans trou ni chevauchement, si l'horodatage permet d'ordonner."""
    if len({m.created_at for m in ordered}) != len(ordered):
        return  # égalités d'horodatage : ordre ambigu, la somme des deltas reste vérifiée par ailleurs
    for previous, current in zip(ordered, ordered[1:]):
        assert current.quantity_before == previous.quantity_after, "chaîne de mouvements rompue"


def assert_only_conflicts(errs, allowed_codes):
    for e in errs:
        assert isinstance(e, ConflictDomainError), f"erreur brute sous concurrence : {e!r}"
        assert code_of(e) in allowed_codes, f"code inattendu {code_of(e)!r}"


def assert_invariants(depot, product, category=FULL):
    stock = row(depot, product, category)
    assert stock.physical_quantity >= 0, "stock physique négatif"
    assert 0 <= stock.reserved_quantity <= stock.physical_quantity, "physical < reserved"
    return stock


# ==========================================================================
# restock en parallèle
# ==========================================================================
@pytest.mark.parametrize("round_", ROUNDS)
class TestParallelRestock:
    def test_missing_line_is_created_once_without_integrity_error_or_lost_update(self, round_):
        depot, product = make_depot(), make_product()
        quantities = list(range(1, THREADS + 1))
        oks, errs = split(run_concurrently([restock_job(depot, product, q) for q in quantities]))

        assert not errs, f"erreur sous concurrence (IntegrityError à la création de ligne ?) : {errs!r}"
        assert DepotStock.objects.filter(depot=depot, product=product, category=FULL).count() == 1
        total = sum(quantities)
        assert row(depot, product).physical_quantity == total, "mise à jour perdue (lost update)"

        ordered = sorted(movements(depot, product), key=lambda m: m.quantity_before)
        assert len(ordered) == THREADS
        assert ordered[0].quantity_before == 0 and ordered[-1].quantity_after == total
        for previous, current in zip(ordered, ordered[1:]):
            assert current.quantity_before == previous.quantity_after, "chaîne de mouvements rompue"
        assert Counter(m.delta for m in ordered) == Counter(quantities)
        assert all(m.movement_type == T.RESTOCK for m in ordered)

    def test_existing_line_reservations_are_never_touched(self, round_):
        depot, product = make_depot(), make_product()
        make_stock(depot=depot, product=product, category=FULL, physical_quantity=5, reserved_quantity=2)
        oks, errs = split(run_concurrently([restock_job(depot, product, 1) for _ in range(THREADS)]))
        assert not errs, errs
        stock = row(depot, product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (5 + THREADS, 2)
        assert len(movements(depot, product)) == THREADS

    def test_each_returned_movement_matches_a_persisted_row(self, round_):
        depot, product = make_depot(), make_product()
        oks, errs = split(run_concurrently([restock_job(depot, product, 2) for _ in range(THREADS)]))
        assert not errs, errs
        returned = {movement.pk for _stock, movement in oks}
        persisted = {m.pk for m in movements(depot, product)}
        assert returned == persisted and len(returned) == THREADS

    def test_distinct_categories_are_created_concurrently_without_interference(self, round_):
        depot, product = make_depot(), make_product()
        calls = [restock_job(depot, product, 3, category=c) for c in StockCategory.values for _ in range(3)]
        oks, errs = split(run_concurrently(calls))
        assert not errs, errs
        for category in StockCategory.values:
            assert row(depot, product, category).physical_quantity == 9
            assert len(movements(depot, product, category)) == 3


# ==========================================================================
# scrap en parallèle
# ==========================================================================
@pytest.mark.parametrize("round_", ROUNDS)
class TestParallelScrap:
    def test_limited_stock_exact_number_of_successes(self, round_):
        depot, product = make_depot(), make_product()
        make_stock(depot=depot, product=product, physical_quantity=10, reserved_quantity=0)
        oks, errs = split(run_concurrently([scrap_job(depot, product, 1) for _ in range(15)]))

        assert len(oks) == 10 and len(errs) == 5, (len(oks), len(errs))
        assert_only_conflicts(errs, {CODE_INSUFFICIENT})
        stock = assert_invariants(depot, product)
        assert stock.physical_quantity == 0
        ordered = movements(depot, product)
        assert len(ordered) == 10 and all(m.delta == -1 for m in ordered)
        assert_contiguous(ordered)

    def test_reserved_stock_is_never_scrapped(self, round_):
        depot, product = make_depot(), make_product()
        make_stock(depot=depot, product=product, physical_quantity=10, reserved_quantity=4)
        oks, errs = split(run_concurrently([scrap_job(depot, product, 1) for _ in range(12)]))

        assert len(oks) == 6 and len(errs) == 6, (len(oks), len(errs))
        assert_only_conflicts(errs, {CODE_INSUFFICIENT})
        stock = assert_invariants(depot, product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (4, 4)
        for e in errs:
            assert e.details["reserved_quantity"] == 4

    def test_larger_scraps_exhaust_the_stock_exactly(self, round_):
        depot, product = make_depot(), make_product()
        make_stock(depot=depot, product=product, physical_quantity=10, reserved_quantity=0)
        oks, errs = split(run_concurrently([scrap_job(depot, product, 3) for _ in range(5)]))
        assert len(oks) == 3 and len(errs) == 2
        assert_only_conflicts(errs, {CODE_INSUFFICIENT})
        assert assert_invariants(depot, product).physical_quantity == 1

    def test_scrap_on_an_empty_missing_line_creates_no_line_and_no_movement(self, round_):
        depot, product = make_depot(), make_product()
        oks, errs = split(run_concurrently([scrap_job(depot, product, 1) for _ in range(6)]))
        assert not oks
        assert_only_conflicts(errs, {CODE_INSUFFICIENT})
        assert not DepotStock.objects.filter(depot=depot, product=product).exists()
        assert not movements(depot, product)


# ==========================================================================
# adjust en parallèle (verrouillage optimiste)
# ==========================================================================
@pytest.mark.parametrize("round_", ROUNDS)
class TestParallelAdjust:
    def test_optimistic_locking_exactly_one_winner(self, round_):
        depot, product = make_depot(), make_product()
        make_stock(depot=depot, product=product, physical_quantity=10, reserved_quantity=0)
        targets = [11 + i for i in range(THREADS)]
        oks, errs = split(run_concurrently(
            [adjust_job(depot, product, target, expected=10) for target in targets]))

        assert len(oks) == 1, f"{len(oks)} ajustements réussis avec la même quantité attendue"
        assert_only_conflicts(errs, {CODE_STOCK_CONFLICT})
        winner_movement = oks[0][1]
        final = assert_invariants(depot, product)
        assert final.physical_quantity == winner_movement.quantity_after
        for e in errs:
            assert e.details["current_physical_quantity"] == final.physical_quantity
        assert len(movements(depot, product)) == 1

    def test_same_target_without_expectation_one_winner_rest_unchanged(self, round_):
        depot, product = make_depot(), make_product()
        make_stock(depot=depot, product=product, physical_quantity=10)
        oks, errs = split(run_concurrently([adjust_job(depot, product, 20) for _ in range(THREADS)]))
        assert len(oks) == 1
        assert_only_conflicts(errs, {CODE_UNCHANGED})
        assert assert_invariants(depot, product).physical_quantity == 20
        assert len(movements(depot, product)) == 1

    def test_adjusting_a_missing_line_concurrently_creates_it_once(self, round_):
        depot, product = make_depot(), make_product()
        oks, errs = split(run_concurrently([adjust_job(depot, product, 7) for _ in range(6)]))
        assert len(oks) == 1
        assert_only_conflicts(errs, {CODE_UNCHANGED})
        assert DepotStock.objects.filter(depot=depot, product=product).count() == 1
        assert assert_invariants(depot, product).physical_quantity == 7

    def test_restock_racing_an_optimistic_adjust_is_serialised(self, round_):
        depot, product = make_depot(), make_product()
        make_stock(depot=depot, product=product, physical_quantity=10)
        calls = [restock_job(depot, product, 1), adjust_job(depot, product, 20, expected=10)]
        oks, errs = split(run_concurrently(calls))
        final = assert_invariants(depot, product).physical_quantity
        if errs:  # le restock est passé en premier : l'ajustement attendait 10
            assert len(errs) == 1 and code_of(errs[0]) == CODE_STOCK_CONFLICT
            assert final == 11
        else:     # l'ajustement est passé en premier, puis le restock
            assert final == 21
        assert len(movements(depot, product)) == len(oks)


# ==========================================================================
# Mélange restock + scrap + adjust
# ==========================================================================
@pytest.mark.parametrize("round_", ROUNDS)
def test_mixed_operations_keep_every_invariant(round_):
    depot, product = make_depot(), make_product()
    make_stock(depot=depot, product=product, physical_quantity=20, reserved_quantity=5)
    calls = (
        [restock_job(depot, product, q) for q in (2, 3, 4, 5, 6, 7)]
        + [scrap_job(depot, product, 3) for _ in range(6)]
        + [adjust_job(depot, product, target) for target in (12, 25, 30, 8)]
    )
    oks, errs = split(run_concurrently(calls))

    assert_only_conflicts(errs, {CODE_INSUFFICIENT, CODE_UNCHANGED, CODE_BELOW_RESERVED})
    stock = assert_invariants(depot, product)
    assert stock.reserved_quantity == 5, "réservation modifiée par un service de stock"

    ordered = movements(depot, product)
    assert len(ordered) == len(oks), "mouvement orphelin ou manquant"
    assert stock.physical_quantity == 20 + sum(m.delta for m in ordered), "somme des deltas incohérente"
    assert_contiguous(ordered)
    returned = {movement.pk for _stock, movement in oks}
    assert returned == {m.pk for m in ordered}
    assert not any(m.delta == 0 for m in ordered)


# ==========================================================================
# Suspension du dépôt vs restock
# ==========================================================================
@pytest.mark.parametrize("round_", ROUNDS)
def test_no_stock_mutation_is_recorded_after_the_depot_is_suspended(round_, admin_user):
    depot, product = make_depot(), make_product()
    suspend = job(change_depot_status, depot=fresh(depot), new_status=DepotStatus.SUSPENDED,
                  actor=admin_user, reason="Contrôle")
    calls = [restock_job(depot, product, 1) for _ in range(8)]
    calls.insert(3, suspend)  # la suspension s'insère au milieu de la rafale
    results = run_concurrently(calls)

    restock_results = [r for i, r in enumerate(results) if i != 3]
    assert results[3][0] == "ok", f"la suspension a échoué : {results[3][1]!r}"
    oks = [v for kind, v in restock_results if kind == "ok"]
    errs = [v for kind, v in restock_results if kind == "err"]
    for e in errs:
        assert isinstance(e, ForbiddenDomainError), f"erreur inattendue : {e!r}"
        assert code_of(e) == CODE_NOT_EDITABLE

    assert fresh(depot).status == DepotStatus.SUSPENDED
    suspended_at = AuditLog.objects.get(action=AUDIT_DEPOT_SUSPENDED, resource_id=str(depot.pk)).created_at
    recorded = movements(depot, product)
    assert len(recorded) == len(oks)
    for m in recorded:
        assert m.created_at <= suspended_at, "mouvement enregistré après la suspension du dépôt"
    stock_total = DepotStock.objects.filter(depot=depot, product=product).first()
    assert (stock_total.physical_quantity if stock_total else 0) == len(oks)


def test_restock_after_a_completed_suspension_is_always_refused(admin_user):
    depot, product = make_depot(), make_product()
    change_depot_status(depot=depot, new_status=DepotStatus.SUSPENDED, actor=admin_user, reason="Contrôle")
    oks, errs = split(run_concurrently([restock_job(depot, product, 1) for _ in range(6)]))
    assert not oks
    for e in errs:
        assert isinstance(e, ForbiddenDomainError) and code_of(e) == CODE_NOT_EDITABLE
    assert not DepotStock.objects.filter(depot=depot).exists()
    assert not StockMovement.objects.filter(depot=depot).exists()


# ==========================================================================
# Isolation entre dépôts, produits et catégories
# ==========================================================================
@pytest.mark.parametrize("round_", ROUNDS)
def test_two_depots_in_parallel_never_interfere(round_):
    depot_a, depot_b, product = make_depot(), make_depot(), make_product()
    make_stock(depot=depot_a, product=product, physical_quantity=6)
    make_stock(depot=depot_b, product=product, physical_quantity=6)
    calls = (
        [restock_job(depot_a, product, 2) for _ in range(5)]
        + [scrap_job(depot_b, product, 1) for _ in range(9)]
    )
    oks, errs = split(run_concurrently(calls))

    assert_only_conflicts(errs, {CODE_INSUFFICIENT})
    assert len(errs) == 3, "le dépôt B devait refuser exactement 3 scraps (6 en stock, 9 demandés)"
    assert row(depot_a, product).physical_quantity == 6 + 10
    assert row(depot_b, product).physical_quantity == 0
    assert len(movements(depot_a, product)) == 5 and len(movements(depot_b, product)) == 6
    assert {m.depot_id for m in StockMovement.objects.all()} == {depot_a.pk, depot_b.pk}


@pytest.mark.parametrize("round_", ROUNDS)
def test_two_products_and_two_categories_in_parallel_never_interfere(round_):
    depot, product_1, product_2 = make_depot(), make_product(), make_product()
    calls = (
        [restock_job(depot, product_1, 1, FULL) for _ in range(4)]
        + [restock_job(depot, product_1, 2, EMPTY) for _ in range(4)]
        + [restock_job(depot, product_2, 3, FULL) for _ in range(4)]
    )
    oks, errs = split(run_concurrently(calls))
    assert not errs, errs
    assert row(depot, product_1, FULL).physical_quantity == 4
    assert row(depot, product_1, EMPTY).physical_quantity == 8
    assert row(depot, product_2, FULL).physical_quantity == 12
    assert StockMovement.objects.filter(depot=depot).count() == 12


# ==========================================================================
# Débit global
# ==========================================================================
def test_a_burst_of_mixed_services_never_deadlocks():
    depot, product = make_depot(), make_product()
    make_stock(depot=depot, product=product, physical_quantity=50, reserved_quantity=10)
    calls = []
    for i in range(30):
        calls.append([restock_job(depot, product, 1), scrap_job(depot, product, 1),
                      adjust_job(depot, product, 20 + i)][i % 3])
    results = run_concurrently(calls, result_timeout=120)
    oks, errs = split(results)
    assert_only_conflicts(errs, {CODE_INSUFFICIENT, CODE_UNCHANGED, CODE_BELOW_RESERVED})
    stock = assert_invariants(depot, product)
    ordered = movements(depot, product)
    assert len(ordered) == len(oks)
    assert stock.physical_quantity == 50 + sum(m.delta for m in ordered)
