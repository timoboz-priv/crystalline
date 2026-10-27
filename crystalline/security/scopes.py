"""Scope strings and wildcard matching.

A scope is `"{type}:{action}"` (e.g. `"Customer:read"`). Either segment
may be `*` to mean "any" — `"Customer:*"` grants every action on
`Customer`, `"*:read"` grants read on every type.

Deliberate exception: `"User"` and `"Role"` (the framework-reserved type
holding credentials, and the pseudo-type scoping role/policy management)
are never covered by a *partial* wildcard like `"*:read"` or `"*:delete"`
— only the literal `"*:*"` (true admin) or an explicit `"User:..."` /
`"Role:..."` grant reaches them. Without this, the built-in `editor` role
(`*:delete`, etc.) would let any editor delete or read other users'
`password_hash`, or redefine roles, the moment `crystalline.tools`
exposes generic CRUD and admin tools. This exception lives here, not in
`crystalline.security.policy`'s default roles, because it must hold for
*any* scope pattern a project defines, not just the built-in ones.
"""

from __future__ import annotations

PROTECTED_TYPES = frozenset({"User", "Role"})


def scope_matches(granted: str, requested: str) -> bool:
    """Does the (possibly wildcarded) `granted` scope cover `requested`?"""
    granted_parts = granted.split(":")
    requested_parts = requested.split(":")
    if len(granted_parts) != len(requested_parts):
        return False

    is_partial_wildcard = granted != "*:*" and granted_parts[0] == "*"
    if requested_parts[0] in PROTECTED_TYPES and is_partial_wildcard:
        return False

    return all(g == "*" or g == r for g, r in zip(granted_parts, requested_parts))
