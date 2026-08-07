from __future__ import annotations

import getpass

from .security import hash_secret


def main() -> None:
    first = getpass.getpass("Arena admin password: ")
    second = getpass.getpass("Repeat password: ")
    if not first or first != second:
        raise SystemExit("Passwords are empty or do not match")
    print(hash_secret(first))


if __name__ == "__main__":
    main()

