"""Send one signed request to the MT5 bridge and verify the signed response.

Standard library only, so it also runs on the backend host. Usage::

    python scripts/check_bridge.py                          # GET /v1/health
    python scripts/check_bridge.py --url https://10.8.0.2:8710 --cafile bridge.crt
    python scripts/check_bridge.py --path /v1/account

The secret is read from the BRIDGE_SECRET environment variable or from ``--env-file``
(default ``.env``). It is never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().upper()] = value.strip().strip('"').strip("'")
    return values


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=None, help="bridge base URL (BRIDGE_URL)")
    parser.add_argument("--path", default="/v1/health", help="path with query to GET")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--cafile", help="CA/self-signed certificate to trust for HTTPS")
    parser.add_argument(
        "--insecure", action="store_true", help="skip TLS verification (testing only)"
    )
    args = parser.parse_args()

    env = _read_env_file(Path(args.env_file))
    secret = os.environ.get("BRIDGE_SECRET") or env.get("BRIDGE_SECRET")
    if not secret:
        print("BRIDGE_SECRET not set (environment or .env)", file=sys.stderr)
        return 2
    base = (
        args.url
        or os.environ.get("BRIDGE_URL")
        or f"http://{env.get('BRIDGE_HOST', '127.0.0.1')}:{env.get('BRIDGE_PORT', '8710')}"
    )
    key = secret.encode("utf-8")

    method, body = "GET", b""
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    canonical = "\n".join([method, args.path, timestamp, nonce, _sha256_hex(body)])
    signature = hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        base.rstrip("/") + args.path,
        method=method,
        headers={"X-FX-Timestamp": timestamp, "X-FX-Nonce": nonce, "X-FX-Signature": signature},
    )

    context = None
    if base.startswith("https"):
        context = ssl.create_default_context(cafile=args.cafile)
        if args.insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as resp:
            status, payload, sig = resp.status, resp.read(), resp.headers.get("X-FX-Signature")
    except urllib.error.HTTPError as exc:
        status, payload, sig = exc.code, exc.read(), exc.headers.get("X-FX-Signature")
    except (urllib.error.URLError, OSError) as exc:
        print(f"Could not reach bridge at {base}: {exc}", file=sys.stderr)
        return 1

    expected = hmac.new(
        key, f"{nonce}\n{status}\n{_sha256_hex(payload)}".encode(), hashlib.sha256
    ).hexdigest()
    sig_ok = sig is not None and hmac.compare_digest(expected, sig)
    print(f"HTTP {status}  response signature: {'valid' if sig_ok else 'INVALID'}")
    try:
        print(json.dumps(json.loads(payload), indent=2))
    except ValueError:
        print(payload.decode("utf-8", "replace"))
    return 0 if (sig_ok and 200 <= status < 300) else 1


if __name__ == "__main__":
    raise SystemExit(main())
