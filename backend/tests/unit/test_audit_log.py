"""Modèle AuditLog : persistance et immutabilité.

Les tests de la classe `TestImmutabilityStrict` vérifient une garantie forte
(bypass via QuerySet). Un échec n'est pas une erreur de test mais un FINDING :
l'immutabilité n'est garantie qu'au niveau de l'instance.
"""
import uuid

import pytest
from django.db import transaction
from django.db.models import ProtectedError
from freezegun import freeze_time

from apps.core.models import AuditLog

pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def make_log(actor, **overrides):
    data = dict(
        actor=actor,
        action="TEST_ACTION",
        resource_type="User",
        resource_id=str(uuid.uuid4()),
        before_state={"is_active": True},
        after_state={"is_active": False},
        reason="raison initiale",
    )
    data.update(overrides)
    return AuditLog.objects.create(**data)


# --------------------------------------------------------------------------
# Persistance
# --------------------------------------------------------------------------
def test_pk_is_a_uuid(admin_user):
    assert isinstance(make_log(admin_user).id, uuid.UUID)


def test_each_log_gets_a_distinct_uuid(admin_user):
    assert make_log(admin_user).id != make_log(admin_user).id


@freeze_time("2026-01-15 10:00:00")
def test_created_at_is_set_automatically_and_timezone_aware(admin_user):
    log = make_log(admin_user)
    log.refresh_from_db()
    assert log.created_at.isoformat().startswith("2026-01-15T10:00:00")
    assert log.created_at.tzinfo is not None


def test_json_states_round_trip(admin_user):
    before = {"nom": "Kouamé", "liste": [1, 2, {"a": None}], "ok": True, "n": 3}
    after = {"emoji": "🔥", "vide": {}, "accents": "éàü"}
    log = make_log(admin_user, before_state=before, after_state=after)
    log.refresh_from_db()
    assert log.before_state == before
    assert log.after_state == after


def test_fields_are_persisted(admin_user):
    log = make_log(admin_user, action="X_Y", resource_type="CustomerSuspension", reason="motif")
    log.refresh_from_db()
    assert (log.actor_id, log.action, log.resource_type, log.reason) == (
        admin_user.pk,
        "X_Y",
        "CustomerSuspension",
        "motif",
    )


# --------------------------------------------------------------------------
# Immutabilité niveau instance
# --------------------------------------------------------------------------
def test_updating_an_existing_log_via_save_is_refused(admin_user):
    log = make_log(admin_user)
    log.reason = "modifiée"
    with pytest.raises(Exception):  # type d'exception non spécifié dans la spec
        with transaction.atomic():
            log.save()
    assert AuditLog.objects.get(pk=log.pk).reason == "raison initiale"


def test_deleting_a_log_instance_is_refused(admin_user):
    log = make_log(admin_user)
    with pytest.raises(Exception):
        with transaction.atomic():
            log.delete()
    assert AuditLog.objects.filter(pk=log.pk).exists()


# --------------------------------------------------------------------------
# Immutabilité niveau QuerySet (garantie forte)
# --------------------------------------------------------------------------
class TestImmutabilityStrict:
    def test_queryset_update_is_refused(self, admin_user):
        log = make_log(admin_user)
        with pytest.raises(Exception):
            with transaction.atomic():
                AuditLog.objects.filter(pk=log.pk).update(reason="falsifié")
        assert AuditLog.objects.get(pk=log.pk).reason == "raison initiale"

    def test_queryset_delete_is_refused(self, admin_user):
        log = make_log(admin_user)
        with pytest.raises(Exception):
            with transaction.atomic():
                AuditLog.objects.filter(pk=log.pk).delete()
        assert AuditLog.objects.filter(pk=log.pk).exists()


# --------------------------------------------------------------------------
# Suppression de l'acteur : le journal doit survivre (pas de CASCADE)
# --------------------------------------------------------------------------
def test_audit_log_survives_actor_deletion(admin_user):
    log = make_log(admin_user)
    try:
        with transaction.atomic():
            admin_user.delete()
    except ProtectedError:
        pass  # PROTECT est acceptable : le journal est conservé
    assert AuditLog.objects.filter(pk=log.pk).exists(), (
        "supprimer l'acteur a détruit le journal d'audit (CASCADE ?)"
    )
