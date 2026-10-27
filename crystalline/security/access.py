"""Checking a token against a required scope at a call boundary.

`check_scope` is the explicit-token form; `requires_scope` is decorator
sugar for an async tool handler, reading the ambient token via
`current_token()` — this is the shape `crystalline.tools` will wrap
auto-generated CRUD tool handlers in.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from .context import current_token
from .token import Token

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def check_scope(token: Token | None, scope: str) -> None:
    if token is None:
        raise PermissionError(f"No token bound; {scope!r} requires authentication")
    if token.is_expired:
        raise PermissionError(f"Token for {token.sub!r} has expired")
    if not token.has_scope(scope):
        raise PermissionError(f"Token for {token.sub!r} lacks required scope {scope!r}")


def requires_scope(scope: str) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            check_scope(current_token(), scope)
            return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
