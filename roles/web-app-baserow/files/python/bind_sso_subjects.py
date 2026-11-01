"""Bind existing Baserow accounts to the Keycloak username the SSO glue keys on.

Env:
    BASEROW_SSO_DIRECTORY_USERS: JSON list of {username, email, emailVerified, id}
        from web-app-keycloak utils/directory_users.yml.
    BOOTSTRAP_ADMIN_USERNAME: Keycloak username of the platform administrator.
    BOOTSTRAP_ADMIN_EMAIL: address of the Baserow account bootstrap_admin.py owns.

Prints one ``skipped <username>: <reason>`` line per local account it leaves
unbound, then ``BIND_STATE=changed`` or ``BIND_STATE=unchanged``.
"""

import json
import os


def plan(directory, accounts, subjects, admin_username, admin_email):
    """Decide which accounts to bind.

    Args:
        directory: keycloak_directory_users entries.
        accounts: Baserow users as ``{id, email}``.
        subjects: bound ``username -> user id`` pairs already stored.
        admin_username: Keycloak username of the platform administrator.
        admin_email: address of the bootstrap administrator account.

    Returns:
        ``(bind, skipped)``: ``(user id, username)`` pairs to store and
        ``(username, reason)`` pairs left unbound.
    """
    by_email = {str(account["email"]).lower(): account for account in accounts}
    bound_users = set(subjects.values())
    bind, skipped = [], []
    entries = [
        {"username": admin_username, "email": admin_email, "emailVerified": True}
    ]
    entries += [entry for entry in directory if entry["username"] != admin_username]
    for entry in entries:
        username = entry["username"]
        account = by_email.get(str(entry["email"]).lower())
        if account is None or subjects.get(username) == account["id"]:
            continue
        if entry["emailVerified"] is not True:
            reason = "the Keycloak email is not verified"
        elif account["id"] in bound_users:
            reason = "the account is linked to another identity"
        elif username in subjects:
            reason = "the identity is linked to another account"
        else:
            bind.append((account["id"], username))
            bound_users.add(account["id"])
            continue
        skipped.append((username, reason))
    return bind, skipped


def main():
    from baserow.infinito_sso_subject.models import SsoSubject
    from django.contrib.auth import get_user_model

    bind, skipped = plan(
        json.loads(os.environ["BASEROW_SSO_DIRECTORY_USERS"]),
        list(get_user_model().objects.values("id", "email")),
        dict(SsoSubject.objects.values_list("username", "user_id")),
        os.environ["BOOTSTRAP_ADMIN_USERNAME"],
        os.environ["BOOTSTRAP_ADMIN_EMAIL"],
    )
    for username, reason in skipped:
        print(f"skipped {username}: {reason}")
    for user_id, username in bind:
        SsoSubject.objects.create(user_id=user_id, username=username)
    print("BIND_STATE=" + ("changed" if bind else "unchanged"))


if __name__ in ("__main__", "django.core.management.commands.shell"):
    main()
