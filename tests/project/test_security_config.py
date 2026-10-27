from crystalline.project.security import (
    build_security_policy,
    describe_security_policy,
    seed_users,
)
from crystalline.security import DEFAULT_ROLES, User, authenticate
from crystalline.storage import InMemoryStorage


def test_build_security_policy_defaults():
    policy = build_security_policy(None)
    assert policy.roles == DEFAULT_ROLES


def test_build_security_policy_with_roles_and_secret():
    policy = build_security_policy(
        {"roles": {"support": ["Order:read"]}, "secret_key": "fixed"}
    )
    assert policy.get_role("support") == ["Order:read"]
    assert policy.secret_key == "fixed"


def test_describe_security_policy_round_trips():
    policy = build_security_policy({"secret_key": "fixed"})
    described = describe_security_policy(policy)
    rebuilt = build_security_policy(described)
    assert rebuilt.roles == policy.roles
    assert rebuilt.secret_key == policy.secret_key


def test_seed_users_creates_missing_users():
    storage = InMemoryStorage()
    seed_users(storage, [{"id": "alice", "password": "secret", "roles": ["admin"]}])
    user = authenticate(storage, "alice", "secret")
    assert user.roles == ["admin"]


def test_seed_users_skips_existing_users():
    storage = InMemoryStorage()
    seed_users(storage, [{"id": "alice", "password": "first"}])
    seed_users(storage, [{"id": "alice", "password": "second"}])
    # still logs in with the original password; second seed was a no-op
    authenticate(storage, "alice", "first")
    assert len(storage.list(User)) == 1


def test_seed_users_handles_none():
    storage = InMemoryStorage()
    seed_users(storage, None)  # should not raise
    assert storage.list(User) == []
