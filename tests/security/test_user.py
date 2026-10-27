import pytest
from pydantic import ValidationError

from crystalline.security import User


def test_defaults():
    user = User(id="ada", password_hash="x")
    assert user.roles == []
    assert user.disabled is False


def test_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        User(id="ada", password_hash="x", nope=True)
