"""Operator commands: `fxrobot <command>`.

    fxrobot serve          run the internal API + trading loop (127.0.0.1:8431)
    fxrobot generate-key   print a new BROKER_CREDENTIALS_KEY

Users are created in Laravel: `php artisan tp:user`.
"""

from __future__ import annotations

import argparse
import secrets

from fxrobot.core.config import get_settings
from fxrobot.core.crypto import generate_key


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "fxrobot.main:create_app",
        factory=True,
        host=args.host or settings.engine_host,
        port=args.port or settings.engine_port,
        proxy_headers=False,
        access_log=False,
        log_config=None,
    )
    return 0


def _generate_key(_: argparse.Namespace) -> int:
    print(generate_key())
    return 0


def _generate_secret(_: argparse.Namespace) -> int:
    print(secrets.token_urlsafe(48))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fxrobot", description="2kPilot trading engine")
    sub = parser.add_subparsers(dest="command", required=True)
    p_serve = sub.add_parser("serve", help="Run the internal API and the trading loop")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=_serve)
    sub.add_parser("generate-key", help="Print a new BROKER_CREDENTIALS_KEY").set_defaults(
        func=_generate_key
    )
    sub.add_parser("generate-secret", help="Print a new ENGINE_API_SECRET").set_defaults(
        func=_generate_secret
    )
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
