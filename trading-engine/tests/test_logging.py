import json
import logging

from fxrobot.core.context import set_correlation_id
from fxrobot.core.logging import MASK, JsonFormatter, mask_data, mask_text


def test_mask_data_masks_sensitive_keys_recursively() -> None:
    data = {
        "login": "123",
        "password": "hunter2",
        "nested": {"api_key": "k", "items": [{"refresh_token": "t"}]},
    }
    masked = mask_data(data)
    assert masked["login"] == "123"
    assert masked["password"] == MASK
    assert masked["nested"]["api_key"] == MASK
    assert masked["nested"]["items"][0]["refresh_token"] == MASK


def test_mask_text_inline_secrets() -> None:
    assert mask_text("connect password=hunter2 server=x") == f"connect password={MASK} server=x"
    assert "abc123" not in mask_text("Authorization: abc123")


def test_json_formatter_includes_correlation_and_masks_extras() -> None:
    set_correlation_id("cid-12345678")
    record = logging.makeLogRecord(
        {
            "msg": "login token=abc",
            "levelname": "INFO",
            "name": "t",
            "password": "p",
            "account": "42",
        }
    )
    payload = json.loads(JsonFormatter().format(record))
    set_correlation_id(None)
    assert payload["correlation_id"] == "cid-12345678"
    assert payload["password"] == MASK
    assert payload["account"] == "42"
    assert "abc" not in payload["message"]
