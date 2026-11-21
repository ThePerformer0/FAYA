"""update_profile et PlatformSetting.load sous concurrence."""
from functools import partial

import pytest
from django.core.exceptions import ObjectDoesNotExist

from apps.accounts import services
from apps.accounts.models import User
from apps.core.exceptions import ConflictDomainError
from apps.core.models import PlatformSetting
from tests.concurrency_helpers import run_concurrently, split
from tests.constants import CODE_PHONE_ALREADY_EXISTS
from tests.domain_asserts import code_of
from tests.helpers import create_user

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]

TARGET_PHONE = "+2250599999999"


@pytest.mark.parametrize("round_", range(5))
def test_two_users_taking_the_same_phone_exactly_one_wins(round_):
    a, b = create_user(), create_user()
    original = {a.pk: a.phone, b.pk: b.phone}
    calls = [partial(services.update_profile, user=u, phone=TARGET_PHONE) for u in (a, b)]

    oks, errs = split(run_concurrently(calls))

    assert len(oks) == 1, f"{len(oks)} mises à jour réussies vers le même téléphone"
    assert len(errs) == 1
    assert isinstance(errs[0], ConflictDomainError), f"erreur brute : {errs[0]!r}"
    assert code_of(errs[0]) == CODE_PHONE_ALREADY_EXISTS
    assert User.objects.filter(phone=TARGET_PHONE).count() == 1
    loser = a if oks[0].pk == b.pk else b
    assert User.objects.get(pk=loser.pk).phone == original[loser.pk], "le perdant a perdu son ancien numéro"


@pytest.mark.parametrize("round_", range(5))
def test_concurrent_updates_of_different_fields_do_not_lose_each_other(round_):
    """Mise à jour perdue : full_name écrasé par un save() complet de l'autre requête."""
    user = create_user()
    stale_for_name = User.objects.get(pk=user.pk)
    stale_for_phone = User.objects.get(pk=user.pk)
    calls = [
        partial(services.update_profile, user=stale_for_name, full_name="Nom Concurrent"),
        partial(services.update_profile, user=stale_for_phone, phone="+2250588888888"),
    ]
    oks, errs = split(run_concurrently(calls))
    assert not errs, errs
    stored = User.objects.get(pk=user.pk)
    assert stored.full_name == "Nom Concurrent", "mise à jour du nom perdue (écrasée)"
    assert stored.phone == "+2250588888888", "mise à jour du téléphone perdue (écrasée)"


def test_many_concurrent_updates_of_the_same_phone_by_the_same_user_are_stable():
    user = create_user()
    calls = [partial(services.update_profile, user=User.objects.get(pk=user.pk), phone=TARGET_PHONE)
             for _ in range(5)]
    oks, errs = split(run_concurrently(calls))
    assert not errs, errs
    assert User.objects.get(pk=user.pk).phone == TARGET_PHONE


def test_platform_setting_load_is_safe_when_the_singleton_is_missing():
    PlatformSetting.objects.all().delete()
    try:
        PlatformSetting.load()
    except ObjectDoesNotExist:
        pytest.skip("load() ne recrée pas le singleton : rien à tester en concurrence")
    PlatformSetting.objects.all().delete()

    oks, errs = split(run_concurrently([PlatformSetting.load for _ in range(6)]))

    assert not errs, f"load() lève sous concurrence : {errs!r}"
    assert {s.pk for s in oks} == {1}
    assert PlatformSetting.objects.count() == 1
