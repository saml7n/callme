"""Tests for the crypto encryption/decryption module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.crypto import decrypt, encrypt


class TestEncryptDecrypt:
    """Round-trip encryption tests."""

    def test_round_trip_plain_text(self):
        plaintext = "hello world"
        token = encrypt(plaintext)
        assert decrypt(token) == plaintext

    def test_round_trip_json(self):
        import json

        data = {"client_id": "abc", "client_secret": "xyz123"}
        plaintext = json.dumps(data)
        token = encrypt(plaintext)
        result = json.loads(decrypt(token))
        assert result == data

    def test_encrypted_value_is_not_plaintext(self):
        plaintext = "secret-password"
        token = encrypt(plaintext)
        assert token != plaintext
        assert "secret-password" not in token

    def test_empty_string(self):
        token = encrypt("")
        assert decrypt(token) == ""

    def test_unicode(self):
        plaintext = "日本語テスト 🎉"
        token = encrypt(plaintext)
        assert decrypt(token) == plaintext

    def test_decrypt_invalid_token_raises(self):
        with pytest.raises(Exception):
            decrypt("not-a-valid-fernet-token")

    def test_uses_env_key_when_set(self):
        """When CALLME_ENCRYPTION_KEY is set, it should be used."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"CALLME_ENCRYPTION_KEY": key}):
            # Force re-initialisation by clearing module cache
            import importlib
            import app.crypto as crypto_mod
            importlib.reload(crypto_mod)

            token = crypto_mod.encrypt("test-value")
            # Should be decryptable with the same key
            f = Fernet(key.encode())
            assert f.decrypt(token.encode()).decode() == "test-value"

            # Clean up: reload with original key
            importlib.reload(crypto_mod)
