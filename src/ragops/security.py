"""Fail-closed API-key authentication without retaining plaintext credentials."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence


def hash_api_key(api_key: str) -> str:
    """Return the canonical digest stored in runtime configuration."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class ApiKeyAuthenticator:
    """Verify a presented key against every configured digest in constant time."""

    def __init__(self, api_key_hashes: Sequence[str]) -> None:
        self._api_key_hashes = tuple(api_key_hashes)

    @property
    def configured(self) -> bool:
        return bool(self._api_key_hashes)

    def accepts(self, api_key: str | None) -> bool:
        if api_key is None:
            return False
        candidate = hash_api_key(api_key)
        matched = False
        for configured_hash in self._api_key_hashes:
            matched = hmac.compare_digest(candidate, configured_hash) or matched
        return matched
