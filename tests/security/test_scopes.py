import pytest

from crystalline.security.scopes import scope_matches


@pytest.mark.parametrize(
    ("granted", "requested", "expected"),
    [
        ("*:*", "Customer:read", True),
        ("*:*", "User:delete", True),
        ("Customer:*", "Customer:read", True),
        ("Customer:*", "Product:read", False),
        ("*:read", "Customer:read", True),
        ("*:read", "Customer:write", False),
        ("Customer:read", "Customer:read", True),
        ("Customer:read", "Product:read", False),
    ],
)
def test_scope_matches(granted, requested, expected):
    assert scope_matches(granted, requested) is expected


@pytest.mark.parametrize("granted", ["*:read", "*:create", "*:update", "*:delete"])
def test_partial_wildcard_never_covers_user(granted):
    assert scope_matches(granted, "User:read") is False


def test_full_wildcard_covers_user():
    assert scope_matches("*:*", "User:delete") is True


def test_explicit_user_grant_covers_user():
    assert scope_matches("User:read", "User:read") is True
    assert scope_matches("User:*", "User:delete") is True


@pytest.mark.parametrize("granted", ["*:read", "*:create", "*:update", "*:delete"])
def test_partial_wildcard_never_covers_role(granted):
    assert scope_matches(granted, "Role:read") is False


def test_full_wildcard_covers_role():
    assert scope_matches("*:*", "Role:delete") is True


def test_explicit_role_grant_covers_role():
    assert scope_matches("Role:read", "Role:read") is True
    assert scope_matches("Role:*", "Role:delete") is True
