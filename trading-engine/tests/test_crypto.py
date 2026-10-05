"""Broker secrets: Laravel-compatible AES-256-GCM.

The cross-language test encrypts with Laravel's own Encrypter (PHP) and
decrypts in Python, and the reverse — so a key mismatch or format drift
between backend/ and trading-engine/ is caught immediately.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fxrobot.core.crypto import SecretBox, SecretBoxError, generate_key

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def test_round_trip_and_tamper_detection() -> None:
    box = SecretBox(generate_key())
    sealed = box.encrypt('{"token":"abc"}')
    assert box.decrypt_json(sealed) == {"token": "abc"}
    assert "abc" not in sealed
    tampered = sealed[:-6] + ("A" if sealed[-6] != "A" else "B") + sealed[-5:]
    with pytest.raises(SecretBoxError):
        box.decrypt(tampered)
    with pytest.raises(SecretBoxError):
        SecretBox(generate_key()).decrypt(sealed)  # wrong key


def test_key_validation_and_repr() -> None:
    with pytest.raises(SecretBoxError):
        SecretBox("")
    with pytest.raises(SecretBoxError):
        SecretBox("base64:c2hvcnQ=")
    assert "base64" not in repr(SecretBox(generate_key()))


PHP = r"""
require 'vendor/autoload.php';
$key = base64_decode(substr($argv[1], 7));
$e = new Illuminate\Encryption\Encrypter($key, 'aes-256-gcm');
if ($argv[2] === 'encrypt') { echo $e->encryptString($argv[3]); }
else { echo $e->decryptString($argv[3]); }
"""


@pytest.mark.skipif(shutil.which("php") is None, reason="PHP not installed")
def test_compatible_with_laravel_encrypter() -> None:
    key = generate_key()
    box = SecretBox(key)
    payload = json.dumps({"token": "pat_secret", "token_kind": "pat"})

    def php(*args: str) -> str:
        return subprocess.run(  # noqa: S603
            ["php", "-r", PHP, "--", key, *args],  # noqa: S607
            cwd=BACKEND,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    from_laravel = php("encrypt", payload)
    assert box.decrypt(from_laravel) == payload
    assert php("decrypt", box.encrypt(payload)) == payload
