"""Broker secrets at rest, compatible with Laravel's Encrypter.

Laravel (backend/) encrypts broker credentials with
`new Encrypter(key, 'aes-256-gcm')->encryptString(json)`; the engine decrypts
the same payloads with the same BROKER_CREDENTIALS_KEY. Payload format:

    base64(json {"iv": b64(12 bytes), "value": b64(ciphertext), "mac": "", "tag": b64(16)})

AES-256-GCM is authenticated: a tampered payload or a wrong key fails to
decrypt instead of returning garbage. The key must never be committed or logged.
"""

from __future__ import annotations

import base64
import binascii
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretBoxError(Exception):
    """Encryption is unavailable or a ciphertext cannot be decrypted."""


def generate_key() -> str:
    """A new key in Laravel's `base64:` notation."""
    return "base64:" + base64.b64encode(os.urandom(32)).decode()


def _parse_key(key: str) -> bytes:
    raw = key.strip()
    if raw.startswith("base64:"):
        raw = raw[len("base64:") :]
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretBoxError("BROKER_CREDENTIALS_KEY is not valid base64") from exc
    if len(decoded) != 32:
        raise SecretBoxError("BROKER_CREDENTIALS_KEY must be 32 bytes (AES-256)")
    return decoded


class SecretBox:
    def __init__(self, key: str) -> None:
        if not key.strip():
            raise SecretBoxError("BROKER_CREDENTIALS_KEY is not configured")
        self._aes = AESGCM(_parse_key(key))

    def encrypt(self, plaintext: str) -> str:
        """Same output format as Laravel's encryptString (used by tests and tools)."""
        iv = os.urandom(12)
        sealed = self._aes.encrypt(iv, plaintext.encode(), None)
        payload = {
            "iv": base64.b64encode(iv).decode(),
            "value": base64.b64encode(sealed[:-16]).decode(),
            "mac": "",
            "tag": base64.b64encode(sealed[-16:]).decode(),
        }
        return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            payload = json.loads(base64.b64decode(ciphertext))
            iv = base64.b64decode(payload["iv"])
            value = base64.b64decode(payload["value"])
            tag = base64.b64decode(payload["tag"])
            return self._aes.decrypt(iv, value + tag, None).decode()
        except (InvalidTag, KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise SecretBoxError("ciphertext could not be decrypted") from exc

    def decrypt_json(self, ciphertext: str) -> dict[str, str]:
        try:
            data = json.loads(self.decrypt(ciphertext))
        except json.JSONDecodeError as exc:
            raise SecretBoxError("credentials payload is not JSON") from exc
        if not isinstance(data, dict):
            raise SecretBoxError("credentials payload must be a JSON object")
        return {str(k): str(v) for k, v in data.items()}

    def __repr__(self) -> str:  # never reveal key material
        return "SecretBox(<redacted>)"
