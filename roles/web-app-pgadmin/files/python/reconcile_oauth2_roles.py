"""Converge the pgAdmin role of every OAuth2 account with the administrator group.

Args:
    PGADMIN_RBAC_ADMINISTRATORS: JSON list of ``{"username", "email", "name"}``
        members of the administrator role group (container exec env).

Every member gets an OAuth2 account with the Administrator role, created ahead
of its first login when missing. Every other OAuth2 account is set to the User
role. Internal accounts, among them the default administrator, are left alone.

Exit: 0 with one ``CHANGED <username>=<role>`` line per written role or
``UNCHANGED`` on stdout, 1 with ``[FAIL]`` on stderr.
"""

import json
import os
import sys


def converge(members: list) -> list:
    """Align the OAuth2 accounts inside an app context.

    Args:
        members: the administrator group members, each with username and email.

    Returns:
        One ``"<username>=<role>"`` entry per account whose role was written.
    """
    from pgadmin.model import Role, User, db
    from pgadmin.tools.user_management import create_user
    from pgadmin.utils.constants import OAUTH2

    administrator = Role.query.filter_by(name="Administrator").one()
    regular = Role.query.filter_by(name="User").one()
    wanted = {member["username"]: member for member in members if member["username"]}
    changes = []

    for username, member in sorted(wanted.items()):
        if User.query.filter_by(username=username, auth_source=OAUTH2).first():
            continue
        if not member["email"]:
            continue
        created, message = create_user(
            {
                "username": username,
                "email": member["email"],
                "role": administrator.id,
                "active": True,
                "auth_source": OAUTH2,
            }
        )
        if not created:
            print(
                f"[FAIL] creating the OAuth2 account {username} failed: {message}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        changes.append(f"{username}=Administrator")

    for account in User.query.filter_by(auth_source=OAUTH2).all():
        target = administrator if account.username in wanted else regular
        if account.roles == [target]:
            continue
        account.roles = [target]
        changes.append(f"{account.username}={target.name}")
    db.session.commit()
    return changes


def main() -> None:
    import config
    from pgadmin import create_app

    raw = os.environ.get("PGADMIN_RBAC_ADMINISTRATORS")
    if raw is None:
        print("[FAIL] PGADMIN_RBAC_ADMINISTRATORS is not set.", file=sys.stderr)
        raise SystemExit(1)

    app = create_app(config.APP_NAME + "-cli")
    with app.test_request_context():
        changes = converge(json.loads(raw))
    print(
        "\n".join(f"CHANGED {change}" for change in changes) if changes else "UNCHANGED"
    )


if __name__ == "__main__":
    main()
