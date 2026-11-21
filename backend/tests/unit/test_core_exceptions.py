"""Hiérarchie des exceptions métier (apps.core.exceptions)."""
import pytest

from apps.core.exceptions import (
    AuthenticationDomainError,
    ConflictDomainError,
    DomainError,
    ForbiddenDomainError,
    NotFoundDomainError,
    ValidationDomainError,
)
from tests.helpers import build_domain_error

pytestmark = pytest.mark.unit

SUBCLASSES = [
    ValidationDomainError,
    AuthenticationDomainError,
    ForbiddenDomainError,
    NotFoundDomainError,
    ConflictDomainError,
]


def test_domain_error_is_an_exception():
    assert issubclass(DomainError, Exception)


@pytest.mark.parametrize("cls", SUBCLASSES, ids=lambda c: c.__name__)
def test_subclasses_inherit_from_domain_error(cls):
    assert issubclass(cls, DomainError)


@pytest.mark.parametrize("cls", SUBCLASSES + [DomainError], ids=lambda c: c.__name__)
def test_can_be_raised_and_caught_by_own_type(cls):
    with pytest.raises(cls):
        raise build_domain_error(cls)


@pytest.mark.parametrize("cls", SUBCLASSES, ids=lambda c: c.__name__)
def test_base_class_catches_every_subclass(cls):
    with pytest.raises(DomainError):
        raise build_domain_error(cls)


@pytest.mark.parametrize("cls", SUBCLASSES, ids=lambda c: c.__name__)
def test_siblings_are_not_confused(cls):
    """`except ConflictDomainError` ne doit pas avaler une ValidationDomainError, etc."""
    for other in SUBCLASSES:
        if other is cls:
            continue
        assert not issubclass(cls, other), f"{cls.__name__} hérite de {other.__name__}"


@pytest.mark.parametrize("cls", SUBCLASSES + [DomainError], ids=lambda c: c.__name__)
def test_str_of_error_is_not_empty(cls):
    assert str(build_domain_error(cls)).strip() != ""
