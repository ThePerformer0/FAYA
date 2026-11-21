"""Inscriptions simultanées : contraintes d'unicité sous concurrence (PostgreSQL réel)."""
import itertools

import pytest
from rest_framework.test import APIClient

from apps.accounts import services
from apps.accounts.models import User
from apps.core.exceptions import ConflictDomainError
from tests.concurrency_helpers import run_concurrently, split
from tests.constants import (
    CODE_ACCOUNT_ALREADY_EXISTS,
    CODE_EMAIL_ALREADY_EXISTS,
    CODE_PHONE_ALREADY_EXISTS,
    URL_REGISTER,
    VALID_PASSWORD,
)
from tests.domain_asserts import code_of

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]

THREADS = 8
ALL_CONFLICT_CODES = {CODE_EMAIL_ALREADY_EXISTS, CODE_PHONE_ALREADY_EXISTS, CODE_ACCOUNT_ALREADY_EXISTS}


def phone(i):
    return f"+22503{i:08d}"


def register(**overrides):
    data = dict(email="race@example.com", phone=phone(1), full_name="Course", password=VALID_PASSWORD)
    data.update(overrides)
    return lambda: services.register_customer(**data)


@pytest.mark.parametrize("round_", range(3))
class TestConcurrentRegistrationService:
    def test_same_email_exactly_one_wins(self, round_):
        results = run_concurrently([register(phone=phone(i)) for i in range(THREADS)])
        oks, errs = split(results)
        assert len(oks) == 1, f"{len(oks)} inscriptions réussies pour le même email"
        for e in errs:
            assert isinstance(e, ConflictDomainError), f"erreur brute sous concurrence : {e!r}"
            assert code_of(e) in {CODE_EMAIL_ALREADY_EXISTS, CODE_ACCOUNT_ALREADY_EXISTS}
        assert User.objects.count() == 1

    def test_same_phone_exactly_one_wins(self, round_):
        results = run_concurrently([register(email=f"p{i}@example.com", phone=phone(7)) for i in range(THREADS)])
        oks, errs = split(results)
        assert len(oks) == 1
        for e in errs:
            assert isinstance(e, ConflictDomainError), f"erreur brute sous concurrence : {e!r}"
            assert code_of(e) in {CODE_PHONE_ALREADY_EXISTS, CODE_ACCOUNT_ALREADY_EXISTS}
        assert User.objects.count() == 1

    def test_same_email_and_phone_exactly_one_wins(self, round_):
        results = run_concurrently([register() for _ in range(THREADS)])
        oks, errs = split(results)
        assert len(oks) == 1
        for e in errs:
            assert isinstance(e, ConflictDomainError), f"erreur brute : {e!r}"
            assert code_of(e) in ALL_CONFLICT_CODES

    def test_emails_differing_only_by_case_exactly_one_wins(self, round_):
        variants = ["Race@Example.com", "race@example.com", "RACE@EXAMPLE.COM", "rAcE@example.com"]
        results = run_concurrently([register(email=v, phone=phone(i)) for i, v in enumerate(variants)])
        oks, errs = split(results)
        assert len(oks) == 1
        assert all(isinstance(e, ConflictDomainError) for e in errs), errs
        assert User.objects.count() == 1


def test_distinct_registrations_all_succeed_without_deadlock():
    results = run_concurrently(
        [register(email=f"ok{i}@example.com", phone=phone(100 + i)) for i in range(THREADS)])
    oks, errs = split(results)
    assert not errs, errs
    assert User.objects.count() == THREADS


def test_api_same_email_one_201_rest_409_never_500():
    def call(i):
        def run():
            client = APIClient()
            client.raise_request_exception = False
            return client.post(URL_REGISTER, {"email": "api-race@example.com", "phone": phone(200 + i),
                                              "full_name": "Course API", "password": VALID_PASSWORD}, format="json")
        return run

    results = run_concurrently([call(i) for i in range(THREADS)])
    oks, errs = split(results)
    assert not errs, errs
    statuses = sorted(r.status_code for r in oks)
    assert statuses.count(201) == 1, statuses
    assert set(statuses) <= {201, 409}, f"statuts inattendus : {statuses}"
    assert User.objects.filter(email="api-race@example.com").count() == 1
