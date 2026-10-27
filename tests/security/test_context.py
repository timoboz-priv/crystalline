from crystalline.security import Token, bind_token, current_token


def test_current_token_defaults_to_none():
    assert current_token() is None


def test_bind_token_sets_and_resets():
    token = Token(sub="ada")
    assert current_token() is None
    with bind_token(token):
        assert current_token() is token
    assert current_token() is None


def test_nested_bind_token_restores_outer_value():
    outer = Token(sub="ada")
    inner = Token(sub="agent:claude-code")

    with bind_token(outer):
        assert current_token() is outer
        with bind_token(inner):
            assert current_token() is inner
        assert current_token() is outer
    assert current_token() is None
