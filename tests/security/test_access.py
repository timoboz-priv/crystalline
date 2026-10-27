import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from crystalline.security import Token, bind_token, check_scope, requires_scope


def test_check_scope_passes_when_granted():
    token = Token(sub="ada", scopes=["Customer:read"])
    check_scope(token, "Customer:read")  # should not raise


def test_check_scope_raises_when_missing():
    token = Token(sub="ada", scopes=["Customer:read"])
    with pytest.raises(PermissionError):
        check_scope(token, "Customer:delete")


def test_check_scope_raises_when_no_token():
    with pytest.raises(PermissionError):
        check_scope(None, "Customer:read")


def test_check_scope_raises_when_expired():
    token = Token(
        sub="ada",
        scopes=["Customer:read"],
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(PermissionError):
        check_scope(token, "Customer:read")


def test_requires_scope_decorator_uses_ambient_token():
    calls = []

    @requires_scope("Customer:create")
    async def create_customer(data):
        calls.append(data)
        return {"ok": True}

    async def run():
        token = Token(sub="ada", scopes=["Customer:create"])
        with bind_token(token):
            return await create_customer({"name": "Ada"})

    result = asyncio.run(run())
    assert result == {"ok": True}
    assert calls == [{"name": "Ada"}]


def test_requires_scope_decorator_blocks_without_scope():
    @requires_scope("Customer:delete")
    async def delete_customer(data):
        return {"ok": True}

    async def run():
        token = Token(sub="ada", scopes=["Customer:read"])
        with bind_token(token):
            return await delete_customer({"id": "c1"})

    with pytest.raises(PermissionError):
        asyncio.run(run())


def test_requires_scope_decorator_blocks_with_no_bound_token():
    @requires_scope("Customer:read")
    async def get_customer(data):
        return {"ok": True}

    with pytest.raises(PermissionError):
        asyncio.run(get_customer({"id": "c1"}))
