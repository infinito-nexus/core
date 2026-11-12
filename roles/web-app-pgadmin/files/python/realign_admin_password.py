"""Converge the pgAdmin administrator account on every deploy.

Usage:
    Piped into the ``/venv/bin/python3 -`` of the running pgAdmin container.

Args:
    PGADMIN_ADMIN_EMAIL: login e-mail of the administrator (container env).
    PGADMIN_ADMIN_PASSWORD_B64: base64 of the UTF-8 password the account must
        accept (container env).
    PGADMIN_SQLITE_PATH: pgAdmin's SQLite configuration database (container env).
    PGADMIN_CONFIG_CONFIG_DATABASE_URI, PGADMIN_CONFIG_SQLITE_PATH, SQLITE_PATH:
        when any is non-empty pgAdmin may keep its accounts elsewhere, so the
        SQLite read is skipped (container env).

Exit: 0 with ``[CHANGED]`` or ``[UNCHANGED]`` on stdout, 1 with ``[FAIL]``
on stderr.
"""

import base64
import binascii
import hashlib
import hmac
import os
import re
import sqlite3
import sys
import unicodedata
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

AB64_SALT = r"(?:[./A-Za-z0-9]{4})*(?:[./A-Za-z0-9]{2,3})?"
PBKDF2_SHA512 = re.compile(
    rf"\$pbkdf2-sha512\$([1-9][0-9]*)\$({AB64_SALT})\$([./A-Za-z0-9]{{86}})"
)
PBKDF2_MAX_ROUNDS = 0xFFFFFFFF
PBKDF2_MAX_SALT_BYTES = 1024
CONFIG_DATABASE_OVERRIDES = (
    "PGADMIN_CONFIG_CONFIG_DATABASE_URI",
    "PGADMIN_CONFIG_SQLITE_PATH",
    "SQLITE_PATH",
)


def ab64_decode(text: str) -> bytes:
    """Decode passlib's adapted base64.

    Args:
        text: unpadded base64 with ``.`` in place of ``+``.

    Returns:
        The decoded bytes.
    """
    return base64.b64decode(text.replace(".", "+") + "=" * (-len(text) % 4))


def ab64_encode(data: bytes) -> str:
    """Encode bytes as passlib's adapted base64.

    Args:
        data: raw bytes.

    Returns:
        Unpadded base64 with ``.`` in place of ``+``.
    """
    return base64.b64encode(data).decode("ascii").rstrip("=").replace("+", ".")


def declared_password(encoded: str) -> str:
    """Decode the password the task hands over as base64.

    Args:
        encoded: base64 of the UTF-8 password.

    Returns:
        The password, byte for byte. Undecodable input exits with a
        ``[FAIL]`` line that carries none of it.
    """
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        print(
            "[FAIL] PGADMIN_ADMIN_PASSWORD_B64 is not base64 of a UTF-8 password.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def config_database_overridden(environ: Mapping[str, str]) -> bool:
    """Tell whether pgAdmin may keep its accounts outside ``PGADMIN_SQLITE_PATH``.

    Args:
        environ: the container environment pgAdmin's ``config`` reads.

    Returns:
        ``True`` when any of ``CONFIG_DATABASE_OVERRIDES`` is non-empty.
    """
    return any(environ.get(name, "") for name in CONFIG_DATABASE_OVERRIDES)


def in_sync(database: str, email: str, password: str) -> bool:
    """Read the drift predicate of ``converge`` without booting pgAdmin.

    Args:
        database: path of pgAdmin's SQLite configuration database.
        email: login e-mail of the administrator.
        password: password the account must accept.

    Returns:
        ``True`` only when exactly one internal account carries ``email``, it
        is active, unlocked, holds the Administrator role, and its stored
        ``pbkdf2_sha512`` hash, within libpass's limits of
        ``PBKDF2_MAX_ROUNDS`` and ``PBKDF2_MAX_SALT_BYTES``, recomputes from
        ``password`` the way Flask-Security hashes it. ``False`` for drift and
        for any state this read cannot judge; ``converge`` decides those
        inside the application.
    """
    path = Path(database)
    if not path.is_file():
        return False
    try:
        with closing(
            sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)
        ) as connection:
            accounts = connection.execute(
                'SELECT id, password, active, locked FROM "user"'
                " WHERE email = ? AND auth_source = ?",
                (email, "internal"),
            ).fetchall()
            salt = connection.execute(
                "SELECT value FROM keys WHERE name = ?", ("SECURITY_PASSWORD_SALT",)
            ).fetchone()
            if len(accounts) != 1 or salt is None:
                return False
            user_id, stored, active, locked = accounts[0]
            administrator = connection.execute(
                "SELECT 1 FROM roles_users JOIN role ON role.id = roles_users.role_id"
                " WHERE roles_users.user_id = ? AND role.name = ?",
                (user_id, "Administrator"),
            ).fetchone()
    except sqlite3.Error:
        return False
    if not active or locked or administrator is None:
        return False
    match = PBKDF2_SHA512.fullmatch(stored) if isinstance(stored, str) else None
    if match is None:
        return False
    rounds, salt_text, checksum = match.groups()
    hash_salt = ab64_decode(salt_text)
    if int(rounds) > PBKDF2_MAX_ROUNDS or len(hash_salt) > PBKDF2_MAX_SALT_BYTES:
        return False
    secret = unicodedata.normalize("NFKD", password)
    signed = base64.b64encode(
        hmac.new(
            salt[0].encode("utf-8"), secret.encode("utf-8"), hashlib.sha512
        ).digest()
    )
    digest = hashlib.pbkdf2_hmac("sha512", signed, hash_salt, int(rounds), 64)
    return hmac.compare_digest(ab64_encode(digest), checksum)


def converge(email: str, password: str) -> str:
    """Create or repair the internal administrator inside an app context.

    Args:
        email: login e-mail of the administrator.
        password: password the account must accept.

    Returns:
        ``"changed"`` after a create or repair, ``"ok"`` when nothing drifted.
    """
    from flask_security.utils import hash_password, verify_password
    from pgadmin.model import Role, User, db
    from pgadmin.tools.user_management import create_user, normalise_password
    from pgadmin.utils.constants import INTERNAL

    admin = Role.query.filter_by(name="Administrator").one()
    user = User.query.filter_by(email=email, auth_source=INTERNAL).first()
    if user is None:
        created, message = create_user(
            {
                "email": email,
                "role": admin.id,
                "active": True,
                "auth_source": INTERNAL,
                "newPassword": password,
                "confirmPassword": password,
            }
        )
        if not created:
            print(
                f"[FAIL] creating the administrator failed: {message}", file=sys.stderr
            )
            raise SystemExit(1)
        return "changed"
    secret = normalise_password(password)
    drift = (
        not verify_password(secret, user.password)
        or not user.active
        or bool(user.locked)
        or admin not in user.roles
    )
    if not drift:
        return "ok"
    user.password = hash_password(secret)
    user.active = True
    user.locked = False
    user.login_attempts = 0
    if admin not in user.roles:
        user.roles.append(admin)
    db.session.commit()
    return "changed"


def converge_in_app(email: str, password: str) -> str:
    """Boot pgAdmin in CLI mode and run ``converge`` in its request context.

    Args:
        email: login e-mail of the administrator.
        password: password the account must accept.

    Returns:
        The state ``converge`` reports.
    """
    import config
    from pgadmin import create_app

    app = create_app(config.APP_NAME + "-cli")
    with app.test_request_context():
        return converge(email, password)


def main() -> None:
    email = os.environ.get("PGADMIN_ADMIN_EMAIL", "")
    encoded = os.environ.get("PGADMIN_ADMIN_PASSWORD_B64", "")
    database = os.environ.get("PGADMIN_SQLITE_PATH", "")
    if not email or not encoded or not database:
        print(
            "[FAIL] PGADMIN_ADMIN_EMAIL, PGADMIN_ADMIN_PASSWORD_B64 or"
            " PGADMIN_SQLITE_PATH is empty.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    password = declared_password(encoded)

    if not config_database_overridden(os.environ) and in_sync(
        database, email, password
    ):
        state = "ok"
    else:
        state = converge_in_app(email, password)
    if state == "changed":
        print(
            "[CHANGED] the pgAdmin administrator was realigned with the declared state"
        )
    else:
        print(
            "[UNCHANGED] the pgAdmin administrator already matches the declared state"
        )


if __name__ == "__main__":
    main()
