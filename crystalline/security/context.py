"""Ambient propagation of the current `Token` through a call stack.

Tool handlers (MCP-shaped: `args: dict` matching a declared schema) have
no slot for an explicit `token` parameter — and shouldn't, since that
would let a model supply its own. Whoever mints or narrows a token binds
it for the duration of a call with `bind_token`; anything deeper in the
stack reads it back with `current_token()`. Works across `asyncio` tasks
and `asyncio.to_thread` (both copy the current `contextvars.Context`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .token import Token

_current_token: ContextVar[Token | None] = ContextVar(
    "crystalline_current_token", default=None
)


def current_token() -> Token | None:
    return _current_token.get()


@contextmanager
def bind_token(token: Token) -> Iterator[Token]:
    reset_point = _current_token.set(token)
    try:
        yield token
    finally:
        _current_token.reset(reset_point)


def rebind_token(token: Token) -> None:
    """Replace the ambient token for the rest of the current context, with
    no corresponding reset. Unlike `bind_token`, this isn't scoped to a
    `with` block — for a long-lived call site (the CLI's `/reload`
    command) that needs to swap the token already bound by an *outer*
    `bind_token(...)` for the remainder of that session, not open a new
    nested scope that would just unwind back to the old token on return.
    """
    _current_token.set(token)
