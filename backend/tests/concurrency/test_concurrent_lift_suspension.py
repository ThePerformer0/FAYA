"""lift_suspension sous concurrence : un seul gagnant, un seul AuditLog."""
from datetime import timedelta
from functools import partial

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import CustomerSuspension, UserRole
from apps.core.exceptions import ConflictDomainError
from apps.core.models import AuditLog
from tests.concurrency_helpers import run_concurrently, split
from tests.constants import CODE_SUSPENSION_ALREADY_LIFTED
from tests.domain_asserts import code_of
from tests.factories import make_suspension
from tests.helpers import create_user

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]

THREADS = 5
ACTION = "CUSTOMER_SUSPENSION_LIFTED"


@pytest.mark.parametrize("round_", range(3))
def test_concurrent_lifts_have_exactly_one_winner(round_):
    customer = create_user()
    admins = [create_user(role=UserRole.ADMIN, is_staff=True) for _ in range(THREADS)]
    now = timezone.now()
    suspension = make_suspension(customer, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=6))
    # instances obsolètes : toutes croient la suspension encore active
    stale = [CustomerSuspension.objects.get(pk=suspension.pk) for _ in range(THREADS)]
    calls = [partial(services.lift_suspension, suspension=s, actor=a, reason=f"levée {i}")
             for i, (s, a) in enumerate(zip(stale, admins))]

    oks, errs = split(run_concurrently(calls))

    assert len(oks) == 1, f"{len(oks)} levées réussies pour une même suspension"
    for e in errs:
        assert isinstance(e, ConflictDomainError), f"erreur brute : {e!r}"
        assert code_of(e) == CODE_SUSPENSION_ALREADY_LIFTED
    assert AuditLog.objects.filter(action=ACTION).count() == 1, "journal d'audit dupliqué ou manquant"

    stored = CustomerSuspension.objects.get(pk=suspension.pk)
    log = AuditLog.objects.get(action=ACTION)
    assert stored.lifted_at is not None
    assert stored.lifted_by_id == oks[0].lifted_by_id == log.actor_id, "état et journal incohérents"
    assert stored.lift_reason == log.reason


def test_lifting_different_suspensions_in_parallel_all_succeed():
    admin = create_user(role=UserRole.ADMIN, is_staff=True)
    now = timezone.now()
    suspensions = [
        make_suspension(create_user(), starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=6))
        for _ in range(THREADS)
    ]
    calls = [partial(services.lift_suspension, suspension=s, actor=admin, reason="geste") for s in suspensions]
    oks, errs = split(run_concurrently(calls))
    assert not errs, errs
    assert AuditLog.objects.filter(action=ACTION).count() == THREADS
