"""Build/describe a project's `SecurityPolicy`, and seed `User` records
into project storage from a project file's `users:` section.

Mirrors `crystalline.project.storage`'s relationship to
`crystalline.storage`: this is the adapter between declarative project
config and real `crystalline.security` objects, which have no notion of
project files themselves.
"""

from __future__ import annotations

from typing import Any

from crystalline.security import SecurityPolicy, User, create_user
from crystalline.storage import Storage


def build_security_policy(config: dict[str, Any] | None) -> SecurityPolicy:
    config = config or {}
    return SecurityPolicy(roles=config.get("roles"), secret_key=config.get("secret_key"))


def describe_security_policy(policy: SecurityPolicy) -> dict[str, Any]:
    """Inverse of `build_security_policy`, for saving a project back out.

    Note this writes `secret_key` back out in plaintext — fine for a
    dev/demo project file you control, not a substitute for real secret
    management in any deployment that matters.
    """
    return {"roles": policy.roles, "secret_key": policy.secret_key}


def seed_users(storage: Storage, users_config: list[dict[str, Any]] | None) -> None:
    """Create any users declared in a project file's `users:` section that
    don't already exist in storage. A user already present (e.g. with a
    password changed since seeding) is left untouched — seeding only ever
    fills gaps, it never overwrites.
    """
    for entry in users_config or []:
        user_id = entry["id"]
        if storage.get(User, user_id) is not None:
            continue
        create_user(storage, user_id, entry["password"], roles=entry.get("roles"))
