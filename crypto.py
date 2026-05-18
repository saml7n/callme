"""Symmetric encryption for integration credentials.

Uses Fernet (AES-128-CBC with HMAC-SHA256) from the ``cryptography`` library.
The encryption key is derived from the ``CALLME_ENCRYPTION_KEY`` env-var.  If
the env-var is missing, a random key is generated on first startup and written
to ``.env`` so it persists.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _derive_key(passphrase: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary passphrase using SHA-256."""
    digest = hashlib.sha256(passphrase.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    key_str = os.getenv("CALLME_ENCRYPTION_KEY", "")
    if not key_str:
        # Generate a random key and persist it
        key_str = Fernet.generate_key().decode()
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        try:
            # Read existing content and check if key already present
            existing = ""
            if env_path.exists():
                existing = env_path.read_text()
            if "CALLME_ENCRYPTION_KEY=" not in existing:
                with open(env_path, "a") as f:
                    f.write(f"\nCALLME_ENCRYPTION_KEY={key_str}\n")
                logger.info("Generated new encryption key and saved to .env")
            else:
                logger.info("Encryption key already in .env but not in env — using file value")
                # Parse the existing key from the file
                for line in existing.splitlines():
                    if line.startswith("CALLME_ENCRYPTION_KEY="):
                        key_str = line.split("=", 1)[1].strip()
                        break
        except OSError:
            logger.warning("Could not write encryption key to .env — using ephemeral key")

    # Accept either a raw Fernet key (url-safe base64, 44 chars) or an
    # arbitrary passphrase (hashed with SHA-256).
    try:
        _fernet = Fernet(key_str.encode() if isinstance(key_str, str) else key_str)
    except (ValueError, Exception):
        _fernet = Fernet(_derive_key(key_str))

    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe base64 token string."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt` back to plaintext."""
    return _get_fernet().decrypt(token.encode()).decode()
