from datetime import datetime, timedelta, timezone

import jwt
import pytest

from crystalline.security import Token


def test_defaults():
    token = Token(sub="ada")
    assert token.sub == "ada"
    assert token.roles == []
    assert token.scopes == []
    assert token.claims == {}
    assert token.expires_at is None
    assert token.is_expired is False


def test_is_expired():
    now = datetime.now(timezone.utc)
    expired = Token(sub="ada", expires_at=now - timedelta(seconds=1))
    not_expired = Token(sub="ada", expires_at=now + timedelta(hours=1))
    assert expired.is_expired is True
    assert not_expired.is_expired is False


def test_has_scope_and_has_role():
    token = Token(sub="ada", roles=["editor"], scopes=["Customer:*", "Product:read"])
    assert token.has_role("editor")
    assert not token.has_role("admin")
    assert token.has_scope("Customer:read")
    assert token.has_scope("Customer:delete")
    assert token.has_scope("Product:read")
    assert not token.has_scope("Product:delete")


def test_token_is_frozen():
    token = Token(sub="ada")
    with pytest.raises(Exception):
        token.sub = "eve"  # type: ignore[misc]


def test_act_as_preserves_sub_and_narrows_scopes():
    token = Token(sub="ada", roles=["editor"], scopes=["Customer:*", "Product:read"])
    delegated = token.act_as("agent:claude-code", scopes=["Customer:read", "Order:read"])

    assert delegated.sub == "ada"  # principal never changes
    assert set(delegated.scopes) == {"Customer:read"}  # Order:read wasn't held, dropped
    assert delegated.act is not None
    assert delegated.act.actor == "agent:claude-code"
    assert delegated.act.scopes == ["Customer:read"]


def test_act_as_without_scopes_inherits_everything():
    token = Token(sub="ada", scopes=["Customer:read"])
    delegated = token.act_as("agent:claude-code")
    assert delegated.scopes == ["Customer:read"]


def test_act_as_chains_delegation():
    token = Token(sub="ada", scopes=["Customer:*"])
    agent_token = token.act_as("agent:claude-code", scopes=["Customer:read"])
    sub_agent_token = agent_token.act_as("agent:sub-task", scopes=["Customer:read"])

    assert sub_agent_token.sub == "ada"
    assert sub_agent_token.act.actor == "agent:sub-task"
    assert sub_agent_token.act.act.actor == "agent:claude-code"


def test_act_as_cannot_escalate():
    token = Token(sub="ada", scopes=["Customer:read"])
    delegated = token.act_as("agent:claude-code", scopes=["Customer:delete", "Customer:read"])
    assert delegated.scopes == ["Customer:read"]


def test_jwt_round_trip():
    token = Token(
        sub="ada",
        roles=["editor"],
        scopes=["Customer:read"],
        claims={"tenant": "acme"},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    encoded = token.to_jwt("secret")
    decoded = Token.from_jwt(encoded, "secret")

    assert decoded.sub == token.sub
    assert decoded.roles == token.roles
    assert decoded.scopes == token.scopes
    assert decoded.claims == token.claims
    # JWT's "exp" is a unix-timestamp integer, so round-tripping loses
    # sub-second precision by design.
    assert decoded.expires_at == token.expires_at.replace(microsecond=0)


def test_jwt_round_trip_with_act_chain():
    token = Token(sub="ada", scopes=["Customer:*"]).act_as(
        "agent:claude-code", scopes=["Customer:read"]
    )
    decoded = Token.from_jwt(token.to_jwt("secret"), "secret")
    assert decoded.act is not None
    assert decoded.act.actor == "agent:claude-code"


def test_jwt_wrong_secret_rejected():
    token = Token(sub="ada")
    encoded = token.to_jwt("secret")
    with pytest.raises(PermissionError):
        Token.from_jwt(encoded, "wrong-secret")


def test_jwt_expired_token_rejected():
    token = Token(sub="ada", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    encoded = token.to_jwt("secret")
    with pytest.raises(PermissionError):
        Token.from_jwt(encoded, "secret")


def test_jwt_tampered_payload_rejected():
    token = Token(sub="ada", scopes=["Customer:read"])
    encoded = token.to_jwt("secret")
    header, payload, signature = encoded.split(".")
    tampered = f"{header}.{payload}x.{signature}"
    with pytest.raises(PermissionError):
        Token.from_jwt(tampered, "secret")


def test_jwt_uses_hs256():
    token = Token(sub="ada")
    encoded = token.to_jwt("secret")
    assert jwt.get_unverified_header(encoded)["alg"] == "HS256"
