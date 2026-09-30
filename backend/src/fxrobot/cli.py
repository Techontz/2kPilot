"""Operator commands: `fxrobot <command>`.

User accounts are created here rather than through a public sign-up
endpoint — a trading system should not expose self-registration.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from fxrobot.core.config import get_settings
from fxrobot.core.crypto import generate_key
from fxrobot.core.errors import ConflictError
from fxrobot.db.session import build_engine, build_session_factory
from fxrobot.models import UserRole
from fxrobot.services import auth


def _read_password(from_stdin: bool) -> str | None:
    if from_stdin:  # for automation: `echo "$PW" | fxrobot create-user ... --password-stdin`
        return sys.stdin.readline().rstrip("\n")
    password = getpass.getpass("Password (min 12 chars, mixed case, a digit): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return None
    return password


def _create_user(args: argparse.Namespace) -> int:
    password = _read_password(args.password_stdin)
    if password is None:
        return 1
    settings = get_settings()
    engine = build_engine(settings)
    try:
        with build_session_factory(engine)() as db:
            user = auth.create_user(
                db,
                email=args.email,
                password=password,
                display_name=args.name,
                role=UserRole(args.role),
            )
            db.commit()
            print(f"Created {user.role.value} user {user.email}")
    except (ValueError, ConflictError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


def _generate_key(_: argparse.Namespace) -> int:
    print(generate_key())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fxrobot", description="2kFX ROBOT operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_user = sub.add_parser("create-user", help="Create a dashboard user")
    p_user.add_argument("--email", required=True)
    p_user.add_argument("--name", required=True)
    p_user.add_argument("--role", choices=[r.value for r in UserRole], default=UserRole.OWNER.value)
    p_user.add_argument(
        "--password-stdin", action="store_true", help="Read the password from stdin"
    )
    p_user.set_defaults(func=_create_user)

    p_key = sub.add_parser("generate-key", help="Print a new SECRET_ENCRYPTION_KEY")
    p_key.set_defaults(func=_generate_key)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
