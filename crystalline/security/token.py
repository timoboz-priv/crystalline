"""`Token`: the thing that represents "who is allowed to do what" as it
flows through the stack.

Modeled on RFC 8693's actor-token pattern: `sub` is always the original
principal (the human user) and never changes through delegation; `act` is
a chainable record of who's actually acting on their behalf right now
(an agent, then maybe a sub-agent), kept for audit/monitoring. Delegating
via `act_as()` can only narrow scopes, never grant new ones, so a
sub-agent can never end up with more power than its parent.

`Token` is the primary, in-process vehicle (passed around as a live
Python object via `crystalline.security.context`). `to_jwt`/`from_jwt`
are there for when a token needs to cross a process boundary or be
persisted verifiably — a thin serialization layer on top, same relationship
as `crystalline.project`'s config objects vs. their YAML/JSON files.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pydantic import BaseModel, ConfigDict, Field

from .scopes import scope_matches

_JWT_ALGORITHM = "HS256"


class Actor(BaseModel):
    """One hop in a delegation chain (e.g. "agent:claude-code")."""

    model_config = ConfigDict(frozen=True)

    actor: str
    scopes: list[str] = Field(default_factory=list)
    issued_at: datetime
    act: Actor | None = None


Actor.model_rebuild()


class Token(BaseModel):
    model_config = ConfigDict(frozen=True)

    sub: str
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    claims: dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    act: Actor | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_scope(self, scope: str) -> bool:
        return any(scope_matches(granted, scope) for granted in self.scopes)

    def act_as(self, actor: str, *, scopes: list[str] | None = None) -> Token:
        """Return a new token for `actor` acting on this token's behalf.

        `scopes`, if given, are filtered down to only those this token
        already grants (`has_scope`) — delegation can only narrow, never
        widen, what the delegate can do. Omit `scopes` to pass everything
        through unchanged.
        """
        if scopes is None:
            narrowed = list(self.scopes)
        else:
            narrowed = [s for s in scopes if self.has_scope(s)]
        new_actor = Actor(
            actor=actor,
            scopes=narrowed,
            issued_at=datetime.now(timezone.utc),
            act=self.act,
        )
        return self.model_copy(update={"scopes": narrowed, "act": new_actor})

    def to_jwt(self, secret: str) -> str:
        payload: dict[str, Any] = {
            "sub": self.sub,
            "roles": self.roles,
            "scopes": self.scopes,
            "claims": self.claims,
            "iat": int(self.issued_at.timestamp()),
        }
        if self.expires_at is not None:
            payload["exp"] = int(self.expires_at.timestamp())
        if self.act is not None:
            payload["act"] = self.act.model_dump(mode="json")
        return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)

    @classmethod
    def from_jwt(cls, token_str: str, secret: str) -> Token:
        try:
            payload = jwt.decode(token_str, secret, algorithms=[_JWT_ALGORITHM])
        except jwt.PyJWTError as exc:
            raise PermissionError(f"Invalid token: {exc}") from exc
        return cls(
            sub=payload["sub"],
            roles=payload.get("roles", []),
            scopes=payload.get("scopes", []),
            claims=payload.get("claims", {}),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at=(
                datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
                if "exp" in payload
                else None
            ),
            act=Actor.model_validate(payload["act"]) if payload.get("act") else None,
        )


DEFAULT_TOKEN_TTL = timedelta(hours=12)
