"""Create backend/.env from .env.example with a freshly generated encryption key.

Never overwrites an existing .env.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.fernet import Fernet

BACKEND = Path(__file__).resolve().parents[1]


def main() -> int:
    target = BACKEND / ".env"
    if target.exists():
        print("backend/.env already exists — left unchanged")
        return 0
    example = (BACKEND.parent / ".env.example").read_text()
    key = Fernet.generate_key().decode()
    content = example.replace("SECRET_ENCRYPTION_KEY=\n", f"SECRET_ENCRYPTION_KEY={key}\n")
    if len(sys.argv) > 1:  # optional DATABASE_URL override
        lines = [f"DATABASE_URL={sys.argv[1]}" if ln.startswith("DATABASE_URL=") else ln
                 for ln in content.splitlines()]
        content = "\n".join(lines) + "\n"
    target.write_text(content)
    target.chmod(0o600)
    print("Created backend/.env with a new SECRET_ENCRYPTION_KEY (back it up; never commit it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
