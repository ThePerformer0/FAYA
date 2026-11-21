"""Assertions utilitaires sur les exceptions métier (DomainError)."""


def code_of(exc):
    return getattr(exc, "code", None)


def message_of(exc):
    return getattr(exc, "message", None) or str(exc)


def assert_domain_error(excinfo, cls, code=None):
    """`excinfo` provient de `with pytest.raises(...) as excinfo`."""
    exc = excinfo.value
    assert isinstance(exc, cls), f"{type(exc).__name__} n'est pas un {cls.__name__}"
    if code is not None:
        assert code_of(exc) == code, f"code {code_of(exc)!r} != {code!r}"
