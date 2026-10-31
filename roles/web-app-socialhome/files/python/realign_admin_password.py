"""Realign the Social Home administrator password with the declared one.

Args:
    SOCIALHOME_REALIGN_USERNAME: administrator username (container env).
    SOCIALHOME_REALIGN_PASSWORD: password the account must accept (container env).

Prints ``[CHANGED]`` after it rewrote the stored hash, ``[UNCHANGED]`` when the
stored hash already accepts the password, and exits with ``[FAIL] <reason>``
otherwise.
"""

import os
import sqlite3
import sys

BUSY_TIMEOUT_MS = 30000


def realign(db_path: str, username: str, password: str) -> str:
    """Rewrite ``username``'s stored hash unless it already accepts ``password``.

    Args:
        db_path: the household's SQLite database.
        username: administrator username.
        password: password the account must accept.

    Returns:
        ``"CHANGED"`` after a rewrite, ``"UNCHANGED"`` when nothing drifted.
    """
    from socialhome.platform.local_credentials import hash_password, verify_password

    connection = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        row = connection.execute(
            "SELECT password_hash FROM platform_users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            sys.exit(f"[FAIL] platform_users holds no row for {username!r}")
        if verify_password(password, row[0]):
            return "UNCHANGED"
        connection.execute(
            "UPDATE platform_users SET password_hash = ? WHERE username = ?",
            (hash_password(password), username),
        )
        connection.commit()
        return "CHANGED"
    finally:
        connection.close()


def main() -> None:
    from socialhome.config import Config

    state = realign(
        Config.from_env().db_path,
        os.environ["SOCIALHOME_REALIGN_USERNAME"],
        os.environ["SOCIALHOME_REALIGN_PASSWORD"],
    )
    print(f"[{state}]")


if __name__ == "__main__":
    main()
