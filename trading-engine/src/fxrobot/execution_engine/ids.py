from __future__ import annotations

import base64
import uuid


def new_client_order_id() -> str:
    """24 chars, [a-z0-9], fits short broker comments. 'fx' prefix marks 2kPilot orders."""
    raw = base64.b32encode(uuid.uuid4().bytes).decode().lower().rstrip("=")
    return "fx" + raw[:22].replace("=", "0")
