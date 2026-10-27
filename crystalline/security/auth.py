"""Password hashing and username/password authentication against a
project's `Storage`.

Uses `bcrypt` directly rather than hand-rolling a KDF — it's the standard
choice (no parameter tuning needed, sane work-factor defaults).
"""

from __future__ import annotations

import bcrypt

from crystalline.storage import Storage

from .user import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_user(
    storage: Storage, user_id: str, password: str, *, roles: list[str] | None = None
) -> User:
    user = User(id=user_id, roles=roles or [], password_hash=hash_password(password))
    return storage.create(user)


def authenticate(storage: Storage, user_id: str, password: str) -> User:
    """Look up `user_id` and check `password` against it.

    Raises `PermissionError` with the same message whether the user
    doesn't exist, is disabled, or the password is wrong — don't give an
    attacker a way to enumerate valid usernames.
    """
    user = storage.get(User, user_id)
    if user is None or user.disabled:
        raise PermissionError("Invalid username or password")
    if not verify_password(password, user.password_hash):
        raise PermissionError("Invalid username or password")
    return user
