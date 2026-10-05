from __future__ import annotations

import base64
import uuid


def new_client_order_id() -> str:
    """24 chars, [a-z0-9], fits MT5's 31-char comment. 'fx' prefix marks 2kFX orders."""
    raw = base64.b32encode(uuid.uuid4().bytes).decode().lower().rstrip("=")
    return "fx" + raw[:22].replace("=", "0")
