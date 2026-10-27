from datetime import timedelta

from crystalline.security import DEFAULT_ROLES, SecurityPolicy, User


def test_default_roles_present():
    policy = SecurityPolicy()
    assert policy.roles == DEFAULT_ROLES


def test_custom_roles_merge_with_defaults():
    policy = SecurityPolicy(roles={"support": ["Order:read", "Order:update"]})
    assert "support" in policy.roles
    assert policy.roles["admin"] == DEFAULT_ROLES["admin"]  # defaults still present


def test_overriding_a_default_role_by_name():
    policy = SecurityPolicy(roles={"viewer": ["Customer:read"]})
    assert policy.roles["viewer"] == ["Customer:read"]


def test_add_get_remove_role():
    policy = SecurityPolicy()
    policy.add_role("support", ["Order:read"])
    assert policy.get_role("support") == ["Order:read"]
    assert policy.remove_role("support") == ["Order:read"]
    assert policy.get_role("support") is None


def test_roles_property_is_a_copy():
    policy = SecurityPolicy()
    snapshot = policy.roles
    snapshot["admin"] = ["nope"]
    assert policy.roles["admin"] == DEFAULT_ROLES["admin"]


def test_secret_key_defaults_to_random_and_differs_per_instance():
    a = SecurityPolicy()
    b = SecurityPolicy()
    assert a.secret_key
    assert a.secret_key != b.secret_key


def test_secret_key_can_be_fixed():
    policy = SecurityPolicy(secret_key="fixed-secret")
    assert policy.secret_key == "fixed-secret"


def test_scopes_for_expands_and_dedupes():
    policy = SecurityPolicy(roles={"a": ["X:read", "Y:read"], "b": ["Y:read", "Z:read"]})
    scopes = policy.scopes_for(["a", "b"])
    assert scopes == ["X:read", "Y:read", "Z:read"]


def test_scopes_for_ignores_unknown_roles():
    policy = SecurityPolicy()
    assert policy.scopes_for(["not-a-role"]) == []


def test_mint_token_from_user_roles():
    policy = SecurityPolicy()
    user = User(id="ada", roles=["editor"], password_hash="x")
    token = policy.mint_token(user)

    assert token.sub == "ada"
    assert token.roles == ["editor"]
    assert set(token.scopes) == set(DEFAULT_ROLES["editor"])
    assert token.expires_at is not None


def test_mint_token_with_no_ttl_never_expires():
    policy = SecurityPolicy()
    user = User(id="ada", roles=["viewer"], password_hash="x")
    token = policy.mint_token(user, ttl=None)
    assert token.expires_at is None
    assert token.is_expired is False


def test_mint_token_custom_ttl():
    policy = SecurityPolicy()
    user = User(id="ada", roles=["viewer"], password_hash="x")
    token = policy.mint_token(user, ttl=timedelta(seconds=0))
    assert token.is_expired is True
