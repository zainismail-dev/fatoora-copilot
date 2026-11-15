"""Small admin commands.

    python -m app.cli add-user clerk@company.sa "Sara Clerk" clerk
    python -m app.cli list-users
"""
from __future__ import annotations

import getpass
import sys

from . import auth, db
from .config import settings


def main(argv: list[str]) -> int:
    db.init(settings.database_path)
    if len(argv) >= 4 and argv[0] == "add-user":
        email, name, role = argv[1], argv[2], argv[3]
        password = getpass.getpass(f"Password for {email} (8+ characters): ")
        user = auth.create_user(email, name, role, password)
        print(f"Created {user['role']} {user['email']}")
        return 0
    if argv[:1] == ["list-users"]:
        for u in db.query("SELECT email, name, role FROM users ORDER BY id"):
            print(f"{u['role']:8} {u['email']}  ({u['name']})")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
