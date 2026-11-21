"""Selectors : get_active_suspension / is_customer_suspended.

Même sémantique de bornes que la propriété `is_currently_active`
(voir test_suspension_model.py). Le test d'invariant ci-dessous garantit
que selector et propriété ne divergent JAMAIS, quelle que soit la règle choisie.
"""
import warnings
from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.accounts.selectors import get_active_suspension, is_customer_suspended
from tests.factories import make_suspension, utc

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

START = utc(2026, 3, 1, 12)
END = utc(2026, 3, 8, 12)
MID = utc(2026, 3, 4, 12)
MICRO = timedelta(microseconds=1)


# --------------------------------------------------------------------------
# Cas de base
# --------------------------------------------------------------------------
def test_no_suspension_returns_none_and_false(customer):
    assert get_active_suspension(user=customer, at=MID) is None
    assert is_customer_suspended(user=customer, at=MID) is False


def test_active_suspension_is_returned(customer):
    s = make_suspension(customer, starts_at=START, ends_at=END)
    assert get_active_suspension(user=customer, at=MID) == s
    assert is_customer_suspended(user=customer, at=MID) is True


def test_other_customers_suspension_is_not_returned(customer, other_customer):
    make_suspension(other_customer, starts_at=START, ends_at=END)
    assert get_active_suspension(user=customer, at=MID) is None
    assert is_customer_suspended(user=customer, at=MID) is False


def test_expired_suspension_is_ignored(customer):
    make_suspension(customer, starts_at=START, ends_at=END)
    assert get_active_suspension(user=customer, at=END + timedelta(days=1)) is None


def test_future_suspension_is_ignored(customer):
    make_suspension(customer, starts_at=START, ends_at=END)
    assert get_active_suspension(user=customer, at=START - timedelta(days=1)) is None


def test_lifted_suspension_is_ignored(customer):
    make_suspension(customer, starts_at=START, ends_at=END, lifted_at=START + timedelta(days=1))
    assert get_active_suspension(user=customer, at=MID) is None
    assert is_customer_suspended(user=customer, at=MID) is False


# --------------------------------------------------------------------------
# Paramètre `at`
# --------------------------------------------------------------------------
def test_default_at_is_now(customer):
    s = make_suspension(customer, starts_at=START, ends_at=END)
    with freeze_time(MID):
        assert get_active_suspension(user=customer) == s
    with freeze_time(END + timedelta(days=1)):
        assert get_active_suspension(user=customer) is None


def test_explicit_at_overrides_the_clock(customer):
    s = make_suspension(customer, starts_at=START, ends_at=END)
    with freeze_time(utc(2030, 1, 1)):  # « maintenant » est hors fenêtre
        assert get_active_suspension(user=customer, at=MID) == s


def test_naive_datetime_is_rejected_or_handled_correctly(customer):
    s = make_suspension(customer, starts_at=START, ends_at=END)
    naive = datetime(2026, 3, 4, 12, 0, 0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            result = get_active_suspension(user=customer, at=naive)
        except (ValueError, TypeError):
            return  # refus explicite : acceptable
    assert result == s


def test_arguments_are_keyword_only(customer):
    with pytest.raises(TypeError):
        get_active_suspension(customer)
    with pytest.raises(TypeError):
        is_customer_suspended(customer)


# --------------------------------------------------------------------------
# Cohérence selector <-> propriété aux bornes
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "moment",
    [START - MICRO, START, START + MICRO, MID, END - MICRO, END, END + MICRO],
    ids=["debut-1us", "debut", "debut+1us", "milieu", "fin-1us", "fin", "fin+1us"],
)
def test_selector_and_property_agree_at_boundaries(customer, moment):
    s = make_suspension(customer, starts_at=START, ends_at=END)
    with freeze_time(moment):
        by_property = s.is_currently_active
        by_selector_now = get_active_suspension(user=customer) is not None
    by_selector_at = get_active_suspension(user=customer, at=moment) is not None
    by_bool_selector = is_customer_suspended(user=customer, at=moment)
    assert by_property == by_selector_now == by_selector_at == by_bool_selector


def test_is_customer_suspended_matches_get_active_suspension(customer):
    make_suspension(customer, starts_at=START, ends_at=END)
    for moment in (START - timedelta(days=1), MID, END + timedelta(days=1)):
        assert is_customer_suspended(user=customer, at=moment) == (
            get_active_suspension(user=customer, at=moment) is not None
        )


# --------------------------------------------------------------------------
# Plusieurs suspensions
# --------------------------------------------------------------------------
def test_overlapping_active_suspensions_pick_one_deterministically(customer):
    s1 = make_suspension(customer, starts_at=START, ends_at=END)
    s2 = make_suspension(customer, starts_at=START + timedelta(days=1), ends_at=END + timedelta(days=10))
    first = get_active_suspension(user=customer, at=MID)
    second = get_active_suspension(user=customer, at=MID)
    assert first in (s1, s2)
    assert first == second
    assert is_customer_suspended(user=customer, at=MID) is True


def test_lifted_one_is_skipped_in_favour_of_the_active_one(customer):
    make_suspension(customer, starts_at=START, ends_at=END, lifted_at=START + timedelta(hours=1))
    active = make_suspension(customer, starts_at=START, ends_at=END + timedelta(days=5))
    assert get_active_suspension(user=customer, at=MID) == active


def test_history_of_expired_suspensions_does_not_mask_a_new_one(customer):
    make_suspension(customer, starts_at=START - timedelta(days=30), ends_at=START - timedelta(days=23))
    current = make_suspension(customer, starts_at=START, ends_at=END)
    assert get_active_suspension(user=customer, at=MID) == current


# --------------------------------------------------------------------------
# Performance : une seule requête
# --------------------------------------------------------------------------
def test_get_active_suspension_runs_one_query(customer, django_assert_max_num_queries):
    make_suspension(customer, starts_at=START, ends_at=END)
    with django_assert_max_num_queries(1):
        get_active_suspension(user=customer, at=MID)


def test_is_customer_suspended_runs_one_query(customer, django_assert_max_num_queries):
    make_suspension(customer, starts_at=START, ends_at=END)
    with django_assert_max_num_queries(1):
        is_customer_suspended(user=customer, at=MID)
