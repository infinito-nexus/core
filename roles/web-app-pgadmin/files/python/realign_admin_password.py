"""Converge the pgAdmin administrator account on every deploy.

Usage:
    Piped into the ``/venv/bin/python3 -`` of the running pgAdmin container.

Args:
    PGADMIN_ADMIN_EMAIL: login e-mail of the administrator (container env).
    PGADMIN_ADMIN_PASSWORD: password the account must accept (container env).

Exit: 0 with ``[CHANGED]`` or ``[UNCHANGED]`` on stdout, 1 with ``[FAIL]``
on stderr.
"""

import os
import sys


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


def main() -> None:
    import config
    from pgadmin import create_app

    email = os.environ.get("PGADMIN_ADMIN_EMAIL", "")
    password = os.environ.get("PGADMIN_ADMIN_PASSWORD", "")
    if not email or not password:
        print(
            "[FAIL] PGADMIN_ADMIN_EMAIL or PGADMIN_ADMIN_PASSWORD is empty.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    app = create_app(config.APP_NAME + "-cli")
    with app.test_request_context():
        state = converge(email, password)
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
