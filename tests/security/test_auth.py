import pytest

from crystalline.security import authenticate, create_user, hash_password, verify_password
from crystalline.security.user import User
from crystalline.storage import InMemoryStorage


def test_hash_and_verify_password():
    hashed = hash_password("hunter2")
    assert hashed != "hunter2"
    assert verify_password("hunter2", hashed)
    assert not verify_password("wrong", hashed)


def test_create_user_stores_hashed_password():
    storage = InMemoryStorage()
    user = create_user(storage, "ada", "hunter2", roles=["editor"])
    assert user.id == "ada"
    assert user.roles == ["editor"]
    assert user.password_hash != "hunter2"
    assert storage.get(User, "ada") == user


def test_authenticate_success():
    storage = InMemoryStorage()
    create_user(storage, "ada", "hunter2")
    user = authenticate(storage, "ada", "hunter2")
    assert user.id == "ada"


def test_authenticate_wrong_password_raises():
    storage = InMemoryStorage()
    create_user(storage, "ada", "hunter2")
    with pytest.raises(PermissionError):
        authenticate(storage, "ada", "wrong")


def test_authenticate_missing_user_raises():
    storage = InMemoryStorage()
    with pytest.raises(PermissionError):
        authenticate(storage, "nobody", "whatever")


def test_authenticate_disabled_user_raises():
    storage = InMemoryStorage()
    user = create_user(storage, "ada", "hunter2")
    storage.update(User, "ada", disabled=True)
    with pytest.raises(PermissionError):
        authenticate(storage, "ada", "hunter2")


def test_missing_user_and_wrong_password_give_the_same_error_message():
    storage = InMemoryStorage()
    create_user(storage, "ada", "hunter2")

    try:
        authenticate(storage, "ada", "wrong")
    except PermissionError as exc:
        wrong_password_message = str(exc)

    try:
        authenticate(storage, "nobody", "whatever")
    except PermissionError as exc:
        missing_user_message = str(exc)

    assert wrong_password_message == missing_user_message
