"""lift_suspension : levée + AuditLog + atomicité.

Les tests « cohérence » (suspension expirée/future, acteur non admin) acceptent
deux comportements métier légitimes (succès OU refus par une DomainError) mais
exigent que l'état de la base et l'AuditLog restent cohérents dans les deux cas.
"""
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from freezegun import freeze_time

from apps.accounts import services
from apps.accounts.models import CustomerSuspension
from apps.accounts.selectors import get_active_suspension
from apps.core.exceptions import (
    ConflictDomainError,
    ForbiddenDomainError,
    ValidationDomainError,
)
from apps.core.models import AuditLog
from tests.constants import CODE_SUSPENSION_ALREADY_LIFTED
from tests.domain_asserts import assert_domain_error
from tests.factories import make_suspension, utc
from tests.helpers import create_user

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

ACTION = "CUSTOMER_SUSPENSION_LIFTED"
NOW = utc(2026, 3, 4, 12)
START = utc(2026, 3, 1, 12)
END = utc(2026, 3, 8, 12)
REASON = "Geste commercial après réclamation"
VALIDATION_ERRORS = (ValidationDomainError, DjangoValidationError)


@pytest.fixture(autouse=True)
def frozen_now():
    with freeze_time(NOW):
        yield


@pytest.fixture
def suspension(customer):
    return make_suspension(customer, starts_at=START, ends_at=END)


def audit_logs():
    return AuditLog.objects.filter(action=ACTION)


def normalized(text):
    return text.replace("_", "").replace(" ", "").lower()


# --------------------------------------------------------------------------
# Levée nominale
# --------------------------------------------------------------------------
class TestLiftSuspension:
    def test_sets_lift_fields_and_persists_them(self, suspension, admin_user):
        result = services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        stored = CustomerSuspension.objects.get(pk=suspension.pk)
        assert result.pk == suspension.pk
        for obj in (result, stored):
            assert obj.lifted_at == NOW
            assert obj.lifted_by_id == admin_user.pk
            assert obj.lift_reason == REASON

    def test_suspension_is_no_longer_active(self, suspension, admin_user, customer):
        assert get_active_suspension(user=customer) is not None
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        assert get_active_suspension(user=customer) is None
        assert CustomerSuspension.objects.get(pk=suspension.pk).is_currently_active is False

    def test_suspension_row_is_kept_for_history(self, suspension, admin_user):
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        assert CustomerSuspension.objects.filter(pk=suspension.pk).exists()

    def test_other_suspensions_are_untouched(self, suspension, admin_user, other_customer):
        other = make_suspension(other_customer, starts_at=START, ends_at=END)
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        other.refresh_from_db()
        assert other.lifted_at is None

    def test_customer_can_be_suspended_again_after_lift(self, suspension, admin_user, customer):
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        again = make_suspension(customer, starts_at=NOW, ends_at=NOW + timedelta(days=7))
        assert get_active_suspension(user=customer) == again

    def test_arguments_are_keyword_only(self, suspension, admin_user):
        with pytest.raises(TypeError):
            services.lift_suspension(suspension, admin_user, REASON)


# --------------------------------------------------------------------------
# AuditLog
# --------------------------------------------------------------------------
class TestLiftSuspensionAudit:
    def test_exactly_one_audit_log_is_written(self, suspension, admin_user):
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        assert audit_logs().count() == 1

    def test_audit_log_identifies_actor_resource_and_reason(self, suspension, admin_user):
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        log = audit_logs().get()
        assert log.actor_id == admin_user.pk
        assert normalized(log.resource_type) == "customersuspension"
        assert str(log.resource_id) == str(suspension.pk)
        assert log.reason == REASON
        assert log.created_at == NOW

    def test_audit_states_describe_the_transition(self, suspension, admin_user):
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        log = audit_logs().get()
        assert isinstance(log.before_state, dict) and isinstance(log.after_state, dict)
        assert log.before_state != log.after_state
        assert "lifted_at" in log.after_state
        assert log.before_state.get("lifted_at") is None

    def test_audit_states_contain_no_secret(self, suspension, admin_user):
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        log = audit_logs().get()
        blob = json.dumps([log.before_state, log.after_state], default=str).lower()
        assert "password" not in blob


# --------------------------------------------------------------------------
# Double levée
# --------------------------------------------------------------------------
class TestLiftTwice:
    def test_second_lift_raises_conflict(self, suspension, admin_user):
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        with pytest.raises(ConflictDomainError) as exc:
            services.lift_suspension(suspension=suspension, actor=admin_user, reason="encore")
        assert_domain_error(exc, ConflictDomainError, CODE_SUSPENSION_ALREADY_LIFTED)

    def test_second_lift_changes_nothing_and_adds_no_audit_log(self, suspension, admin_user):
        second_admin = create_user(role="ADMIN", is_staff=True)
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        with pytest.raises(ConflictDomainError):
            services.lift_suspension(suspension=suspension, actor=second_admin, reason="autre")
        stored = CustomerSuspension.objects.get(pk=suspension.pk)
        assert stored.lifted_by_id == admin_user.pk
        assert stored.lift_reason == REASON
        assert audit_logs().count() == 1

    def test_stale_in_memory_instance_cannot_bypass_the_check(self, suspension, admin_user):
        """L'instance obsolète (lifted_at=None en mémoire) doit être revérifiée en base."""
        stale = CustomerSuspension.objects.get(pk=suspension.pk)
        services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
        with pytest.raises(ConflictDomainError) as exc:
            services.lift_suspension(suspension=stale, actor=admin_user, reason="doublon")
        assert_domain_error(exc, ConflictDomainError, CODE_SUSPENSION_ALREADY_LIFTED)
        assert audit_logs().count() == 1


# --------------------------------------------------------------------------
# Validation / cas limites
# --------------------------------------------------------------------------
class TestLiftSuspensionEdgeCases:
    @pytest.mark.parametrize("reason", ["", "   ", "\n\t"], ids=["vide", "espaces", "blancs"])
    def test_blank_reason_is_rejected_without_side_effects(self, suspension, admin_user, reason):
        with pytest.raises(VALIDATION_ERRORS):
            services.lift_suspension(suspension=suspension, actor=admin_user, reason=reason)
        suspension.refresh_from_db()
        assert suspension.lifted_at is None
        assert audit_logs().count() == 0

    @pytest.mark.parametrize("window", ["expiree", "future"])
    def test_lifting_a_non_current_suspension_is_consistent(self, customer, admin_user, window):
        if window == "expiree":
            s = make_suspension(customer, starts_at=NOW - timedelta(days=10), ends_at=NOW - timedelta(days=3))
        else:
            s = make_suspension(customer, starts_at=NOW + timedelta(days=3), ends_at=NOW + timedelta(days=10))
        try:
            services.lift_suspension(suspension=s, actor=admin_user, reason=REASON)
        except (ConflictDomainError, ValidationDomainError, ForbiddenDomainError):
            s.refresh_from_db()
            assert s.lifted_at is None
            assert audit_logs().count() == 0
            return
        s.refresh_from_db()
        assert s.lifted_at is not None
        assert audit_logs().count() == 1

    def test_non_admin_actor_is_consistent(self, suspension, other_customer):
        """Hypothèse n°2 : soit accepté (permission portée par l'API), soit Forbidden."""
        try:
            services.lift_suspension(suspension=suspension, actor=other_customer, reason=REASON)
        except (ForbiddenDomainError, ValidationDomainError):
            suspension.refresh_from_db()
            assert suspension.lifted_at is None
            assert audit_logs().count() == 0
            return
        suspension.refresh_from_db()
        assert suspension.lifted_by_id == other_customer.pk
        assert audit_logs().get().actor_id == other_customer.pk


# --------------------------------------------------------------------------
# Atomicité
# --------------------------------------------------------------------------
def test_audit_failure_rolls_back_the_lift(suspension, admin_user):
    with patch.object(AuditLog, "save", side_effect=RuntimeError("audit indisponible")):
        with pytest.raises(Exception):
            services.lift_suspension(suspension=suspension, actor=admin_user, reason=REASON)
    stored = CustomerSuspension.objects.get(pk=suspension.pk)
    assert stored.lifted_at is None
    assert stored.lifted_by_id is None
    assert not stored.lift_reason
    assert audit_logs().count() == 0
