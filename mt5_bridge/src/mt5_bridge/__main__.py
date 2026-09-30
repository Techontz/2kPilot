"""``mt5-bridge`` console entry point."""

from __future__ import annotations

import argparse
import sys

import uvicorn
from pydantic import ValidationError

from .app import create_app
from .config import Settings
from .logutil import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mt5-bridge", description="2kFX MT5 bridge")
    parser.add_argument("--env-file", default=".env", help="settings file (default: .env)")
    parser.add_argument("--host", help="bind address (BRIDGE_HOST, default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port (BRIDGE_PORT, default 8710)")
    parser.add_argument("--ssl-certfile", help="TLS certificate (BRIDGE_SSL_CERTFILE)")
    parser.add_argument("--ssl-keyfile", help="TLS private key (BRIDGE_SSL_KEYFILE)")
    args = parser.parse_args(argv)

    try:
        settings = Settings(_env_file=args.env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        print(f"Invalid configuration:\n{exc}", file=sys.stderr)
        return 2
    overrides = {
        "bridge_host": args.host,
        "bridge_port": args.port,
        "bridge_ssl_certfile": args.ssl_certfile,
        "bridge_ssl_keyfile": args.ssl_keyfile,
    }
    settings = settings.model_copy(update={k: v for k, v in overrides.items() if v is not None})
    if bool(settings.bridge_ssl_certfile) != bool(settings.bridge_ssl_keyfile):
        print("Both --ssl-certfile and --ssl-keyfile are required for TLS", file=sys.stderr)
        return 2

    configure_logging(settings.bridge_log_level)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.bridge_host,
        port=settings.bridge_port,
        ssl_certfile=settings.bridge_ssl_certfile,
        ssl_keyfile=settings.bridge_ssl_keyfile,
        workers=1,
        proxy_headers=False,
        server_header=False,
        access_log=False,
        log_config=None,
        timeout_keep_alive=15,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
