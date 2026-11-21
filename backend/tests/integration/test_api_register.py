"""POST /api/v1/auth/register/"""
import itertools
import json
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from freezegun import freeze_time
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts import services
from apps.accounts.models import User, UserRole
from tests.api_helpers import assert_refresh_cookie, cookie_value, morsel
from tests.constants import (
    CODE_EMAIL_ALREADY_EXISTS,
    CODE_PHONE_ALREADY_EXISTS,
    CODE_ACCOUNT_ALREADY_EXISTS,
    CODE_VALIDATION,
    PASSWORD_ALL_NUMERIC,
    PASSWORD_COMMON,
    PASSWORD_TOO_SHORT,
    URL_ME,
    URL_REGISTER,
    VALID_PASSWORD,
)
from tests.helpers import assert_unified_error

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_seq = itertools.count(70000)
FORBIDDEN_USER_KEYS = {"password", "password_hash", "refresh_token", "refresh", "is_staff", "is_superuser"}


def valid_payload(**overrides):
    n = next(_seq)
    data = {
        "email": f"reg{n}@example.com",
        "phone": f"+22502{n:08d}",
        "full_name": "Awa Traoré",
        "password": VALID_PASSWORD,
    }
    data.update(overrides)
    return data


def post(client, data):
    return client.post(URL_REGISTER, data, format="json")


def digits(base):
    return "+" + "".join(chr(base + int(d)) for d in "2250102030405")


BAD_PHONES = {
    "sans_plus": "2250102030405",
    "zero_local": "0102030405",
    "double_zero": "00225102030405",
    "plus_zero": "+0225102030405",
    "7_chiffres": "+1234567",
    "16_chiffres": "+1234567890123456",
    "espaces_internes": "+225 01 02 03 04 05",
    "tirets": "+225-01-02-03-04-05",
    "lettres": "+225abcdefgh",
    "double_plus": "++2250102030405",
    "chiffres_arabes": digits(0x0660),
    "pleine_largeur": digits(0xFF10),
}
BAD_EMAILS = ["pas-un-email", "a@", "@b.com", "a b@example.com", "a@b", "x" * 300 + "@example.com"]


# ==========================================================================
# Succès
# ==========================================================================
class TestRegisterSuccess:
    def test_returns_201_with_exactly_access_token_and_user(self, api_client):
        response = post(api_client, valid_payload())
        assert response.status_code == 201, response.content
        assert set(response.json()) == {"access_token", "user"}

    def test_user_payload(self, api_client):
        data = valid_payload()
        user = post(api_client, data).json()["user"]
        assert {"id", "email", "phone", "full_name", "role"} <= set(user)
        assert user["email"].lower() == data["email"].lower()
        assert user["phone"] == data["phone"]
        assert user["full_name"] == data["full_name"]
        assert user["role"] == UserRole.CUSTOMER
        assert not (FORBIDDEN_USER_KEYS & set(user))

    def test_refresh_cookie_is_set_with_secure_attributes(self, api_client):
        data = valid_payload()
        response = post(api_client, data)
        assert_refresh_cookie(response, User.objects.get(phone=data["phone"]))

    def test_refresh_token_never_appears_in_the_body(self, api_client):
        response = post(api_client, valid_payload())
        assert cookie_value(response) not in response.content.decode()

    def test_password_is_never_returned(self, api_client):
        response = post(api_client, valid_payload())
        assert VALID_PASSWORD not in response.content.decode()

    def test_access_token_belongs_to_the_new_user_and_works_on_me(self, api_client):
        data = valid_payload()
        body = post(api_client, data).json()
        user = User.objects.get(phone=data["phone"])
        assert AccessToken(body["access_token"])[jwt_settings.USER_ID_CLAIM] == str(user.pk)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access_token']}")
        me = api_client.get(URL_ME)
        assert me.status_code == 200
        assert me.json()["email"].lower() == data["email"].lower()

    def test_user_is_persisted_as_a_plain_customer(self, api_client):
        data = valid_payload()
        post(api_client, data)
        user = User.objects.get(phone=data["phone"])
        assert user.role == UserRole.CUSTOMER
        assert (user.is_active, user.is_staff, user.is_superuser) == (True, False, False)
        assert user.password != VALID_PASSWORD and user.check_password(VALID_PASSWORD)

    def test_two_registrations_get_distinct_tokens(self, api_client):
        a = post(api_client, valid_payload())
        b = post(api_client, valid_payload())
        assert a.json()["access_token"] != b.json()["access_token"]
        assert cookie_value(a) != cookie_value(b)

    def test_unicode_and_hostile_full_name_are_stored_verbatim(self, api_client):
        name = "Kouamé <script>alert(1)</script>'; DROP TABLE accounts_user;-- 🙂"
        data = valid_payload(full_name=name)
        response = post(api_client, data)
        assert response.status_code == 201
        assert User.objects.get(phone=data["phone"]).full_name == name
        assert response.json()["user"]["full_name"] == name


# ==========================================================================
# Mass assignment
# ==========================================================================
@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "ADMIN"),
        ("role", "DEPOT_MANAGER"),
        ("is_staff", True),
        ("is_superuser", True),
        ("is_active", False),
        ("id", str(uuid.uuid4())),
        ("created_at", "2000-01-01T00:00:00Z"),
        ("managed_depot_id", str(uuid.uuid4())),
    ],
)
def test_privileged_fields_are_ignored_or_rejected_never_applied(api_client, field, value):
    data = valid_payload(**{field: value})
    response = post(api_client, data)
    if response.status_code == 201:
        user = User.objects.get(phone=data["phone"])
        assert user.role == UserRole.CUSTOMER
        assert (user.is_active, user.is_staff, user.is_superuser) == (True, False, False)
        assert str(user.pk) != str(value)
        assert user.created_at.year != 2000
    else:
        assert_unified_error(response, 400)
        assert not User.objects.filter(phone=data["phone"]).exists()


# ==========================================================================
# Validation
# ==========================================================================
class TestRegisterValidation:
    @pytest.mark.parametrize("field", ["email", "phone", "full_name", "password"])
    def test_missing_field(self, api_client, field):
        data = valid_payload()
        data.pop(field)
        body = assert_unified_error(post(api_client, data), 400, CODE_VALIDATION)
        assert field in json.dumps(body["details"])
        assert User.objects.count() == 0

    @pytest.mark.parametrize("field", ["email", "phone", "full_name", "password"])
    @pytest.mark.parametrize("bad", [None, "", [], {}, True], ids=["null", "vide", "liste", "objet", "bool"])
    def test_null_empty_or_wrongly_typed_field(self, api_client, field, bad):
        body = assert_unified_error(post(api_client, valid_payload(**{field: bad})), 400, CODE_VALIDATION)
        assert field in json.dumps(body["details"])
        assert User.objects.count() == 0

    @pytest.mark.parametrize("email", BAD_EMAILS, ids=lambda e: e[:20])
    def test_invalid_email(self, api_client, email):
        body = assert_unified_error(post(api_client, valid_payload(email=email)), 400, CODE_VALIDATION)
        assert "email" in json.dumps(body["details"])
        assert User.objects.count() == 0

    @pytest.mark.parametrize("phone", list(BAD_PHONES.values()), ids=list(BAD_PHONES))
    def test_invalid_phone(self, api_client, phone):
        body = assert_unified_error(post(api_client, valid_payload(phone=phone)), 400, CODE_VALIDATION)
        assert "phone" in json.dumps(body["details"])
        assert User.objects.count() == 0

    @pytest.mark.parametrize(
        "password",
        [PASSWORD_TOO_SHORT, PASSWORD_COMMON, PASSWORD_ALL_NUMERIC],
        ids=["trop_court", "commun", "tout_numerique"],
    )
    def test_weak_password(self, api_client, password):
        body = assert_unified_error(post(api_client, valid_payload(password=password)), 400, CODE_VALIDATION)
        assert "password" in json.dumps(body["details"])
        assert User.objects.count() == 0

    def test_password_too_similar_to_user_attributes(self, api_client):
        data = valid_payload(email="kouame.jean@example.com", full_name="Kouame Jean",
                             password="kouame.jean@example.com")
        assert_unified_error(post(api_client, data), 400, CODE_VALIDATION)
        assert User.objects.count() == 0

    def test_whitespace_only_full_name(self, api_client):
        assert_unified_error(post(api_client, valid_payload(full_name="   ")), 400, CODE_VALIDATION)

    def test_full_name_longer_than_max_length(self, api_client):
        max_length = User._meta.get_field("full_name").max_length
        if not max_length:
            pytest.skip("full_name sans max_length")
        assert_unified_error(
            post(api_client, valid_payload(full_name="x" * (max_length + 1))), 400, CODE_VALIDATION
        )

    @pytest.mark.parametrize("field", ["email", "phone", "full_name", "password"])
    def test_nul_character_is_a_400_not_a_500(self, api_client, field):
        base = valid_payload()
        response = post(api_client, {**base, field: base[field][:3] + "\x00" + base[field][3:]})
        assert_unified_error(response, 400, CODE_VALIDATION)

    @pytest.mark.parametrize("field,suffix", [("phone", "\n"), ("phone", " "), ("email", " "), ("email", "\n")])
    def test_trailing_whitespace_is_trimmed_or_rejected_never_stored(self, api_client, field, suffix):
        data = valid_payload()
        data[field] = data[field] + suffix
        response = post(api_client, data)
        if response.status_code == 201:
            stored = getattr(User.objects.get(email__iexact=data["email"].strip()), field)
            assert stored == stored.strip() and "\n" not in stored
        else:
            assert_unified_error(response, 400, CODE_VALIDATION)

    def test_very_long_password_is_not_a_server_error(self, api_client):
        assert post(api_client, valid_payload(password="Aa1!" * 250)).status_code < 500

    def test_huge_full_name_is_not_a_server_error(self, api_client):
        assert post(api_client, valid_payload(full_name="x" * 1_000_000)).status_code < 500


# ==========================================================================
# Corps de requête malformé
# ==========================================================================
class TestRegisterMalformedBody:
    def test_invalid_json(self, api_client):
        r = api_client.post(URL_REGISTER, data="{pas du json", content_type="application/json")
        assert_unified_error(r, 400)

    def test_unsupported_media_type(self, api_client):
        r = api_client.post(URL_REGISTER, data="email=a@b.c", content_type="text/plain")
        assert_unified_error(r, 415)

    @pytest.mark.parametrize("body", ["", "[]", "null", '"texte"', "42"], ids=["vide", "liste", "null", "chaine", "nombre"])
    def test_non_object_json_body(self, api_client, body):
        r = api_client.post(URL_REGISTER, data=body, content_type="application/json")
        assert_unified_error(r, 400)

    def test_empty_object(self, api_client):
        assert_unified_error(post(api_client, {}), 400, CODE_VALIDATION)


# ==========================================================================
# Conflits
# ==========================================================================
class TestRegisterConflicts:
    def test_duplicate_email(self, api_client, customer):
        r = post(api_client, valid_payload(email=customer.email))
        assert_unified_error(r, 409, CODE_EMAIL_ALREADY_EXISTS)
        assert morsel(r) is None or not morsel(r).value
        assert User.objects.count() == 1

    def test_duplicate_email_different_case(self, api_client, customer):
        r = post(api_client, valid_payload(email=customer.email.upper()))
        assert_unified_error(r, 409, CODE_EMAIL_ALREADY_EXISTS)

    def test_duplicate_phone(self, api_client, customer):
        r = post(api_client, valid_payload(phone=customer.phone))
        assert_unified_error(r, 409, CODE_PHONE_ALREADY_EXISTS)
        assert User.objects.count() == 1

    def test_duplicate_email_and_phone(self, api_client, customer):
        r = post(api_client, valid_payload(email=customer.email, phone=customer.phone))
        body = assert_unified_error(r, 409)
        assert body["code"] in {CODE_EMAIL_ALREADY_EXISTS, CODE_PHONE_ALREADY_EXISTS, CODE_ACCOUNT_ALREADY_EXISTS}

    def test_conflict_response_does_not_leak_password_or_hash(self, api_client, customer):
        r = post(api_client, valid_payload(email=customer.email))
        text = r.content.decode()
        assert VALID_PASSWORD not in text and customer.password not in text


# ==========================================================================
# Endpoint public
# ==========================================================================
class TestRegisterIsPublic:
    @pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
    def test_other_methods_are_405(self, api_client, method):
        r = getattr(api_client, method)(URL_REGISTER)
        assert_unified_error(r, 405)

    def test_garbage_bearer_header_does_not_block_registration(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer ceci.n.est.pas.un.jwt")
        assert post(api_client, valid_payload()).status_code == 201

    def test_expired_bearer_header_does_not_block_registration(self, api_client, customer):
        token = services.issue_auth_tokens(user=customer).access_token
        later = datetime.now(dt_timezone.utc) + jwt_settings.ACCESS_TOKEN_LIFETIME + timedelta(minutes=5)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        with freeze_time(later):
            assert post(api_client, valid_payload()).status_code == 201
