"""`SecurityPolicy`: a project's roles (name -> granted scope patterns)
and the secret used to sign/verify JWTs minted from it.

Built-in roles are always present unless a project redefines them by
name — same "sensible defaults, overridable" shape as
`crystalline.project.storage`'s backend config.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from .token import DEFAULT_TOKEN_TTL, Token
from .user import User

DEFAULT_ROLES: dict[str, list[str]] = {
    "admin": ["*:*"],
    "editor": ["*:create", "*:read", "*:update", "*:delete"],
    "viewer": ["*:read"],
}


class SecurityPolicy:
    def __init__(
        self,
        *,
        roles: dict[str, list[str]] | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._roles: dict[str, list[str]] = {
            name: list(scopes) for name, scopes in DEFAULT_ROLES.items()
        }
        if roles:
            self._roles.update({name: list(scopes) for name, scopes in roles.items()})
        if secret_key is not None:
            self.secret_key = secret_key
        else:
            self.secret_key = secrets.token_hex(32)

    def add_role(self, name: str, scopes: list[str]) -> None:
        self._roles[name] = list(scopes)

    def get_role(self, name: str) -> list[str] | None:
        scopes = self._roles.get(name)
        return list(scopes) if scopes is not None else None

    def remove_role(self, name: str) -> list[str] | None:
        return self._roles.pop(name, None)

    @property
    def roles(self) -> dict[str, list[str]]:
        return {name: list(scopes) for name, scopes in self._roles.items()}

    def scopes_for(self, role_names: list[str]) -> list[str]:
        """Expand role names into their granted scopes (deduped, unknown
        role names are silently skipped)."""
        scopes: list[str] = []
        for name in role_names:
            for scope in self._roles.get(name, []):
                if scope not in scopes:
                    scopes.append(scope)
        return scopes

    def mint_token(
        self, user: User, *, ttl: timedelta | None = DEFAULT_TOKEN_TTL
    ) -> Token:
        now = datetime.now(timezone.utc)
        return Token(
            sub=user.id,
            roles=list(user.roles),
            scopes=self.scopes_for(user.roles),
            issued_at=now,
            expires_at=(now + ttl) if ttl is not None else None,
        )
