from ragops.security import ApiKeyAuthenticator, hash_api_key


def test_api_key_authenticator_hashes_and_checks_every_configured_key() -> None:
    authenticator = ApiKeyAuthenticator([hash_api_key("first-key"), hash_api_key("second-key")])

    assert authenticator.configured is True
    assert authenticator.accepts("first-key") is True
    assert authenticator.accepts("second-key") is True
    assert authenticator.accepts("wrong-key") is False
    assert authenticator.accepts(None) is False


def test_empty_api_key_authenticator_is_explicitly_unconfigured() -> None:
    authenticator = ApiKeyAuthenticator([])

    assert authenticator.configured is False
    assert authenticator.accepts("anything") is False
