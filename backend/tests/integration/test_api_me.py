"""GET / PATCH /api/v1/auth/me/"""
import json
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings as jwt_settings

from apps.accounts import services
from apps.accounts.models import User, UserRole
from tests.api_helpers import (
    alg_none,
    bearer,
    forge_payload,
    set_cookie,
    tamper_signature,
    wrong_key,
)
from tests.constants import (
    CODE_AUTHENTICATION_FAILED,
    CODE_PHONE_ALREADY_EXISTS,
    CODE_TOKEN_EXPIRED,
    CODE_UNAUTHENTICATED,
    CODE_VALIDATION,
    URL_ME,
    VALID_PASSWORD,
)
from tests.factories import make_suspension, utc
from tests.helpers import assert_unified_error, create_user

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

ME_KEYS = {
    "id", "email", "phone", "full_name", "role",
    "active_suspension", "managed_depot_id", "created_at",
}
MICRO = timedelta(microseconds=1)


def digits(base):
    return "+" + "".join(chr(base + int(d)) for d in "2250102030405")


def snapshot(user):
    u = User.objects.get(pk=user.pk)
    return {
        "email": u.email, "phone": u.phone, "full_name": u.full_name, "role": u.role,
        "is_staff": u.is_staff, "is_superuser": u.is_superuser, "is_active": u.is_active,
        "password": u.password, "created_at": u.created_at,
    }


# ==========================================================================
# GET : authentification
# ==========================================================================
class TestMeAuthentication:
    def test_anonymous(self, api_client, db):
        assert_unified_error(api_client.get(URL_ME), 401, CODE_UNAUTHENTICATED)

    @pytest.mark.parametrize(
        "header",
        ["Bearer", "Bearer ", "Bearer a b", "Bearer null", "Basic dXNlcjpwYXNz", "Token abc"],
        ids=["sans_jeton", "espace", "deux_jetons", "null", "basic", "token"],
    )
    def test_malformed_authorization_header(self, api_client, db, header):
        api_client.credentials(HTTP_AUTHORIZATION=header)
        assert_unified_error(api_client.get(URL_ME), 401)

    def test_garbage_token(self, api_client, db):
        bearer(api_client, "ceci.n.est.pas.un.jwt")
        body = assert_unified_error(api_client.get(URL_ME), 401)
        assert body["code"] in {CODE_AUTHENTICATION_FAILED, CODE_UNAUTHENTICATED}

    def test_expired_access_token(self, auth_client, customer):
        client = auth_client(customer)
        later = datetime.now(dt_timezone.utc) + jwt_settings.ACCESS_TOKEN_LIFETIME + timedelta(minutes=1)
        with freeze_time(later):
            r = client.get(URL_ME)
        assert_unified_error(r, 401, CODE_TOKEN_EXPIRED)

    @pytest.mark.parametrize("forge", [tamper_signature, alg_none, wrong_key],
                             ids=["signature", "alg_none", "autre_cle"])
    def test_forged_access_token(self, api_client, customer, forge):
        token = services.issue_auth_tokens(user=customer).access_token
        bearer(api_client, forge(token))
        assert_unified_error(api_client.get(URL_ME), 401)

    def test_forged_user_id(self, api_client, customer, other_customer):
        token = services.issue_auth_tokens(user=customer).access_token
        bearer(api_client, forge_payload(token, **{jwt_settings.USER_ID_CLAIM: str(other_customer.pk)}))
        assert_unified_error(api_client.get(URL_ME), 401)

    def test_refresh_token_is_not_accepted_as_access_token(self, api_client, customer):
        bearer(api_client, services.issue_auth_tokens(user=customer).refresh_token)
        assert_unified_error(api_client.get(URL_ME), 401)

    def test_token_of_a_deleted_user(self, auth_client, customer):
        client = auth_client(customer)
        customer.delete()
        assert_unified_error(client.get(URL_ME), 401)

    def test_token_of_a_disabled_user(self, auth_client, customer):
        client = auth_client(customer)
        customer.is_active = False
        customer.save()
        assert_unified_error(client.get(URL_ME), 401)

    def test_refresh_cookie_alone_does_not_authenticate(self, api_client, customer):
        set_cookie(api_client, services.issue_auth_tokens(user=customer).refresh_token)
        assert_unified_error(api_client.get(URL_ME), 401, CODE_UNAUTHENTICATED)


# ==========================================================================
# GET : contenu
# ==========================================================================
class TestMeGet:
    def test_exact_documented_structure(self, auth_client, customer):
        r = auth_client(customer).get(URL_ME)
        assert r.status_code == 200
        assert set(r.json()) == ME_KEYS

    def test_values(self, auth_client, customer):
        data = auth_client(customer).get(URL_ME).json()
        assert data["id"] == str(customer.pk)
        assert data["email"] == customer.email
        assert data["phone"] == customer.phone
        assert data["full_name"] == customer.full_name
        assert data["role"] == UserRole.CUSTOMER
        assert parse_datetime(data["created_at"]) == customer.created_at

    @pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DEPOT_MANAGER, UserRole.ADMIN])
    def test_every_role_gets_the_same_structure(self, auth_client, role):
        user = create_user(role=role)
        data = auth_client(user).get(URL_ME).json()
        assert set(data) == ME_KEYS and data["role"] == role

    def test_managed_depot_id_is_null_for_a_customer(self, auth_client, customer):
        assert auth_client(customer).get(URL_ME).json()["managed_depot_id"] is None

    def test_no_secret_is_exposed(self, auth_client, customer):
        text = auth_client(customer).get(URL_ME).content.decode()
        assert customer.password not in text and "password" not in text.lower()

    def test_user_only_sees_their_own_profile(self, auth_client, customer, other_customer):
        assert auth_client(other_customer).get(URL_ME).json()["id"] == str(other_customer.pk)
        assert auth_client(customer).get(URL_ME).json()["id"] == str(customer.pk)

    def test_database_changes_are_reflected_immediately(self, auth_client, customer):
        client = auth_client(customer)
        User.objects.filter(pk=customer.pk).update(phone="+2250799999999", full_name="Changé en base")
        data = client.get(URL_ME).json()
        assert (data["phone"], data["full_name"]) == ("+2250799999999", "Changé en base")

    def test_role_is_read_from_database_not_frozen_in_the_token(self, auth_client, customer):
        client = auth_client(customer)
        User.objects.filter(pk=customer.pk).update(role=UserRole.ADMIN)
        assert client.get(URL_ME).json()["role"] == UserRole.ADMIN

    @pytest.mark.parametrize("method", ["post", "put", "delete"])
    def test_other_methods_are_405(self, auth_client, customer, method):
        assert_unified_error(getattr(auth_client(customer), method)(URL_ME), 405)


# ==========================================================================
# GET : active_suspension
# ==========================================================================
class TestMeActiveSuspension:
    NOW = utc(2026, 3, 4, 12)
    START = utc(2026, 3, 1, 12)
    END = utc(2026, 3, 8, 12)

    def get_me(self, auth_client, user, at=None):
        with freeze_time(at or self.NOW):
            return auth_client(user).get(URL_ME).json()

    def test_null_when_never_suspended(self, auth_client, customer):
        assert self.get_me(auth_client, customer)["active_suspension"] is None

    def test_exposes_the_active_suspension(self, auth_client, customer):
        make_suspension(customer, starts_at=self.START, ends_at=self.END)
        suspension = self.get_me(auth_client, customer)["active_suspension"]
        assert isinstance(suspension, dict)
        assert parse_datetime(suspension["ends_at"]) == self.END
        assert suspension["reason"] == "MANUAL"

    def test_does_not_expose_internal_fields(self, auth_client, customer, admin_user):
        make_suspension(customer, starts_at=self.START, ends_at=self.END)
        suspension = self.get_me(auth_client, customer)["active_suspension"]
        assert not ({"customer", "customer_id", "lifted_by", "lift_reason"} & set(suspension))

    @pytest.mark.parametrize(
        "window",
        [
            (utc(2026, 2, 1), utc(2026, 2, 8)),
            (utc(2026, 4, 1), utc(2026, 4, 8)),
        ],
        ids=["expiree", "future"],
    )
    def test_null_when_not_current(self, auth_client, customer, window):
        make_suspension(customer, starts_at=window[0], ends_at=window[1])
        assert self.get_me(auth_client, customer)["active_suspension"] is None

    def test_null_when_lifted(self, auth_client, customer, admin_user):
        s = make_suspension(customer, starts_at=self.START, ends_at=self.END)
        with freeze_time(self.NOW):
            services.lift_suspension(suspension=s, actor=admin_user, reason="geste")
        assert self.get_me(auth_client, customer)["active_suspension"] is None

    def test_other_customers_suspension_is_not_leaked(self, auth_client, customer, other_customer):
        make_suspension(other_customer, starts_at=self.START, ends_at=self.END)
        assert self.get_me(auth_client, customer)["active_suspension"] is None
        assert self.get_me(auth_client, other_customer)["active_suspension"] is not None

    def test_boundaries_follow_the_selector(self, auth_client, customer):
        make_suspension(customer, starts_at=self.START, ends_at=self.END)
        assert self.get_me(auth_client, customer, self.START)["active_suspension"] is not None
        assert self.get_me(auth_client, customer, self.END - MICRO)["active_suspension"] is not None
        assert self.get_me(auth_client, customer, self.END)["active_suspension"] is None

    def test_query_count_does_not_grow_with_suspension_history(self, auth_client, customer):
        client = auth_client(customer)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                assert client.get(URL_ME).status_code == 200
            return len(ctx)

        baseline = count()
        now = timezone.now()
        for i in range(10):
            make_suspension(customer, starts_at=now - timedelta(days=100 + 10 * i),
                            ends_at=now - timedelta(days=93 + 10 * i))
        make_suspension(customer, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=6))
        with_history = count()
        assert with_history == baseline, "N+1 sur l'historique des suspensions"
        assert with_history <= 4


# ==========================================================================
# PATCH : nominal
# ==========================================================================
class TestMePatch:
    def test_full_name_only(self, auth_client, customer):
        phone = customer.phone
        r = auth_client(customer).patch(URL_ME, {"full_name": "Nouveau Nom"}, format="json")
        assert r.status_code == 200, r.content
        assert set(r.json()) == ME_KEYS
        assert r.json()["full_name"] == "Nouveau Nom"
        stored = User.objects.get(pk=customer.pk)
        assert (stored.full_name, stored.phone) == ("Nouveau Nom", phone)

    def test_phone_only(self, auth_client, customer):
        name = customer.full_name
        r = auth_client(customer).patch(URL_ME, {"phone": "+2250700000042"}, format="json")
        assert r.status_code == 200
        stored = User.objects.get(pk=customer.pk)
        assert (stored.full_name, stored.phone) == (name, "+2250700000042")

    def test_both_fields(self, auth_client, customer):
        r = auth_client(customer).patch(
            URL_ME, {"full_name": "Autre Nom", "phone": "+2250700000043"}, format="json"
        )
        assert r.status_code == 200
        assert (r.json()["full_name"], r.json()["phone"]) == ("Autre Nom", "+2250700000043")

    def test_empty_object_changes_nothing(self, auth_client, customer):
        before = snapshot(customer)
        r = auth_client(customer).patch(URL_ME, {}, format="json")
        assert r.status_code == 200
        assert snapshot(customer) == before

    def test_response_matches_a_subsequent_get(self, auth_client, customer):
        client = auth_client(customer)
        patched = client.patch(URL_ME, {"full_name": "Cohérence"}, format="json").json()
        assert client.get(URL_ME).json() == patched

    def test_same_phone_as_own_is_accepted(self, auth_client, customer):
        r = auth_client(customer).patch(URL_ME, {"phone": customer.phone}, format="json")
        assert r.status_code == 200

    def test_patch_is_idempotent(self, auth_client, customer):
        client = auth_client(customer)
        first = client.patch(URL_ME, {"full_name": "Idem"}, format="json")
        second = client.patch(URL_ME, {"full_name": "Idem"}, format="json")
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()

    def test_suspended_customer_can_still_edit_their_profile(self, auth_client, customer):
        now = timezone.now()
        make_suspension(customer, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=6))
        r = auth_client(customer).patch(URL_ME, {"full_name": "Suspendu mais éditable"}, format="json")
        assert r.status_code == 200

    def test_response_exposes_active_suspension(self, auth_client, customer):
        now = timezone.now()
        make_suspension(customer, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=6))
        r = auth_client(customer).patch(URL_ME, {"full_name": "Avec suspension"}, format="json")
        assert r.json()["active_suspension"] is not None

    def test_unicode_and_hostile_name_stored_verbatim(self, auth_client, customer):
        name = "Zoé <b>gras</b>'; DROP TABLE accounts_user;-- 🙂"
        r = auth_client(customer).patch(URL_ME, {"full_name": name}, format="json")
        assert r.status_code == 200 and r.json()["full_name"] == name
        assert User.objects.get(pk=customer.pk).full_name == name

    def test_no_secret_is_exposed(self, auth_client, customer):
        r = auth_client(customer).patch(URL_ME, {"full_name": "Secret ?"}, format="json")
        assert "password" not in r.content.decode().lower()


# ==========================================================================
# PATCH : validation
# ==========================================================================
class TestMePatchValidation:
    @pytest.mark.parametrize("field", ["full_name", "phone"])
    @pytest.mark.parametrize("bad", ["", [], {}, True], ids=["vide", "liste", "objet", "bool"])
    def test_empty_or_wrongly_typed_field(self, auth_client, customer, field, bad):
        before = snapshot(customer)
        r = auth_client(customer).patch(URL_ME, {field: bad}, format="json")
        assert_unified_error(r, 400, CODE_VALIDATION)
        assert field in json.dumps(r.json()["details"])
        assert snapshot(customer) == before

    @pytest.mark.parametrize("field", ["full_name", "phone"])
    def test_null_is_rejected_or_treated_as_no_op(self, auth_client, customer, field):
        before = snapshot(customer)
        r = auth_client(customer).patch(URL_ME, {field: None}, format="json")
        if r.status_code != 200:
            assert_unified_error(r, 400, CODE_VALIDATION)
        assert snapshot(customer) == before

    def test_whitespace_only_full_name(self, auth_client, customer):
        before = snapshot(customer)
        assert_unified_error(
            auth_client(customer).patch(URL_ME, {"full_name": "   "}, format="json"), 400, CODE_VALIDATION
        )
        assert snapshot(customer) == before

    def test_full_name_longer_than_max_length(self, auth_client, customer):
        max_length = User._meta.get_field("full_name").max_length
        if not max_length:
            pytest.skip("full_name sans max_length")
        r = auth_client(customer).patch(URL_ME, {"full_name": "x" * (max_length + 1)}, format="json")
        assert_unified_error(r, 400, CODE_VALIDATION)

    @pytest.mark.parametrize(
        "phone",
        ["0102030405", "00225102030405", "+0225102030405", "+1234567", "+1234567890123456",
         "+225 01 02 03 04 05", "+225-01-02-03-04-05", "+225abcdefgh", "++2250102030405",
         digits(0x0660), digits(0xFF10)],
        ids=["local", "double_zero", "plus_zero", "7_chiffres", "16_chiffres", "espaces",
             "tirets", "lettres", "double_plus", "arabes", "pleine_largeur"],
    )
    def test_invalid_phone(self, auth_client, customer, phone):
        before = snapshot(customer)
        r = auth_client(customer).patch(URL_ME, {"phone": phone}, format="json")
        assert_unified_error(r, 400, CODE_VALIDATION)
        assert "phone" in json.dumps(r.json()["details"])
        assert snapshot(customer) == before

    @pytest.mark.parametrize("field,value", [("full_name", "Ab\x00cd"), ("phone", "+22507\x0000000000")])
    def test_nul_character_is_a_400_not_a_500(self, auth_client, customer, field, value):
        r = auth_client(customer).patch(URL_ME, {field: value}, format="json")
        assert_unified_error(r, 400, CODE_VALIDATION)

    @pytest.mark.parametrize("suffix", ["\n", " "])
    def test_trailing_whitespace_in_phone_is_trimmed_or_rejected_never_stored(self, auth_client, customer, suffix):
        r = auth_client(customer).patch(URL_ME, {"phone": "+2250700000077" + suffix}, format="json")
        if r.status_code == 200:
            assert User.objects.get(pk=customer.pk).phone == "+2250700000077"
        else:
            assert_unified_error(r, 400, CODE_VALIDATION)

    def test_invalid_json(self, auth_client, customer):
        r = auth_client(customer).patch(URL_ME, data="{pas du json", content_type="application/json")
        assert_unified_error(r, 400)

    def test_unsupported_media_type(self, auth_client, customer):
        r = auth_client(customer).patch(URL_ME, data="full_name=x", content_type="text/plain")
        assert_unified_error(r, 415)

    @pytest.mark.parametrize("body", ["[]", "null", '"texte"', "42"], ids=["liste", "null", "chaine", "nombre"])
    def test_non_object_body(self, auth_client, customer, body):
        r = auth_client(customer).patch(URL_ME, data=body, content_type="application/json")
        assert_unified_error(r, 400)


# ==========================================================================
# PATCH : conflits
# ==========================================================================
class TestMePatchConflicts:
    def test_phone_used_by_another_user(self, auth_client, customer, other_customer):
        before = snapshot(customer)
        r = auth_client(customer).patch(URL_ME, {"phone": other_customer.phone}, format="json")
        assert_unified_error(r, 409, CODE_PHONE_ALREADY_EXISTS)
        assert snapshot(customer) == before

    def test_conflict_is_atomic_full_name_is_not_applied(self, auth_client, customer, other_customer):
        before = snapshot(customer)
        r = auth_client(customer).patch(
            URL_ME, {"full_name": "Ne Doit Pas Passer", "phone": other_customer.phone}, format="json"
        )
        assert r.status_code == 409
        assert snapshot(customer) == before


# ==========================================================================
# PATCH : mass assignment / prise de contrôle de compte
# ==========================================================================
FORBIDDEN_FIELDS = [
    ("email", "hacked@example.com"),
    ("role", "ADMIN"),
    ("is_staff", True),
    ("is_superuser", True),
    ("is_active", False),
    ("password", "Hacked!Passw0rd-999"),
    ("created_at", "2000-01-01T00:00:00Z"),
    ("managed_depot_id", str(uuid.uuid4())),
    ("active_suspension", None),
]


class TestMePatchForbiddenFields:
    @pytest.mark.parametrize("field,value", FORBIDDEN_FIELDS, ids=[f for f, _ in FORBIDDEN_FIELDS])
    def test_forbidden_field_alone_is_ignored_or_rejected(self, auth_client, customer, field, value):
        before = snapshot(customer)
        r = auth_client(customer).patch(URL_ME, {field: value}, format="json")
        assert r.status_code in (200, 400)
        if r.status_code == 400:
            assert_unified_error(r, 400)
        assert snapshot(customer) == before
        assert User.objects.get(pk=customer.pk).check_password(VALID_PASSWORD)

    @pytest.mark.parametrize("field,value", FORBIDDEN_FIELDS, ids=[f for f, _ in FORBIDDEN_FIELDS])
    def test_forbidden_field_next_to_a_valid_one(self, auth_client, customer, field, value):
        before = snapshot(customer)
        r = auth_client(customer).patch(URL_ME, {"full_name": "Valide", field: value}, format="json")
        after = snapshot(customer)
        if r.status_code == 200:
            assert after["full_name"] == "Valide"
            after["full_name"] = before["full_name"]
        else:
            assert_unified_error(r, 400)
        assert after == before

    def test_cannot_target_another_user_through_the_body(self, auth_client, customer, other_customer):
        victim_before = snapshot(other_customer)
        r = auth_client(customer).patch(
            URL_ME, {"id": str(other_customer.pk), "full_name": "Usurpation"}, format="json"
        )
        assert r.status_code in (200, 400)
        assert snapshot(other_customer) == victim_before
        assert User.objects.get(pk=customer.pk).pk != other_customer.pk

    def test_email_takeover_attempt_keeps_login_intact(self, auth_client, customer, other_customer):
        auth_client(customer).patch(URL_ME, {"email": other_customer.email}, format="json")
        assert User.objects.filter(email=other_customer.email).count() == 1
        assert User.objects.get(pk=other_customer.pk).email == other_customer.email


# ==========================================================================
# PATCH : accès
# ==========================================================================
class TestMePatchAccess:
    def test_anonymous(self, api_client, db):
        assert_unified_error(api_client.patch(URL_ME, {"full_name": "X"}, format="json"), 401, CODE_UNAUTHENTICATED)

    def test_expired_token(self, auth_client, customer):
        client = auth_client(customer)
        later = datetime.now(dt_timezone.utc) + jwt_settings.ACCESS_TOKEN_LIFETIME + timedelta(minutes=1)
        with freeze_time(later):
            r = client.patch(URL_ME, {"full_name": "X"}, format="json")
        assert_unified_error(r, 401, CODE_TOKEN_EXPIRED)

    def test_disabled_user_cannot_patch(self, auth_client, customer):
        client = auth_client(customer)
        customer.is_active = False
        customer.save()
        before = snapshot(customer)
        assert_unified_error(client.patch(URL_ME, {"full_name": "X"}, format="json"), 401)
        assert snapshot(customer) == before

    def test_put_is_not_allowed(self, auth_client, customer):
        r = auth_client(customer).put(URL_ME, {"full_name": "X", "phone": customer.phone}, format="json")
        assert_unified_error(r, 405)

    def test_cookie_alone_cannot_patch(self, api_client, customer):
        set_cookie(api_client, services.issue_auth_tokens(user=customer).refresh_token)
        assert_unified_error(api_client.patch(URL_ME, {"full_name": "X"}, format="json"), 401)
