"""Encryption of sensitive values (broker credentials) at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256, authenticated). The key comes from
SECRET_ENCRYPTION_KEY and must never be committed or logged. MultiFernet
allows key rotation: new values are encrypted with the first key, and any
listed key can decrypt.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretBoxError(Exception):
    """Raised when encryption is unavailable or a ciphertext cannot be decrypted."""


def generate_key() -> str:
    return Fernet.generate_key().decode()


class SecretBox:
    def __init__(self, keys: str) -> None:
        key_list = [k.strip() for k in keys.split(",") if k.strip()]
        if not key_list:
            raise SecretBoxError("SECRET_ENCRYPTION_KEY is not configured")
        try:
            self._fernet = MultiFernet([Fernet(k.encode()) for k in key_list])
        except (ValueError, TypeError) as exc:
            raise SecretBoxError("SECRET_ENCRYPTION_KEY is not a valid Fernet key") from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretBoxError("ciphertext could not be decrypted") from exc

    def __repr__(self) -> str:  # never reveal key material
        return "SecretBox(<redacted>)"
