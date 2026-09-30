import pytest

from fxrobot.core.crypto import SecretBox, SecretBoxError, generate_key
from fxrobot.core.security import (
    hash_password,
    hash_token,
    tokens_match,
    validate_password_strength,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("Correct-Horse-42")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "Correct-Horse-42")
    assert not verify_password(hashed, "correct-horse-42")


def test_verify_password_without_hash_is_false() -> None:
    assert not verify_password(None, "anything")
    assert not verify_password("not-a-hash", "anything")


@pytest.mark.parametrize(
    ("password", "ok"),
    [
        ("short1A", False),
        ("alllowercase123", False),
        ("NoDigitsHereAtAll", False),
        ("Good-Password-9", True),
    ],
)
def test_password_strength(password: str, ok: bool) -> None:
    assert (validate_password_strength(password) == []) is ok


def test_token_hashing() -> None:
    assert tokens_match("abc", hash_token("abc"))
    assert not tokens_match("abd", hash_token("abc"))


def test_secret_box_roundtrip() -> None:
    box = SecretBox(generate_key())
    ciphertext = box.encrypt("broker-password")
    assert "broker-password" not in ciphertext
    assert box.decrypt(ciphertext) == "broker-password"
    assert "key" not in repr(box).lower() or "redacted" in repr(box)


def test_secret_box_rejects_wrong_key() -> None:
    ciphertext = SecretBox(generate_key()).encrypt("x")
    with pytest.raises(SecretBoxError):
        SecretBox(generate_key()).decrypt(ciphertext)


def test_secret_box_requires_valid_key() -> None:
    with pytest.raises(SecretBoxError):
        SecretBox("")
    with pytest.raises(SecretBoxError):
        SecretBox("not-a-fernet-key")


def test_secret_box_key_rotation() -> None:
    old, new = generate_key(), generate_key()
    ciphertext = SecretBox(old).encrypt("x")
    assert SecretBox(f"{new},{old}").decrypt(ciphertext) == "x"
