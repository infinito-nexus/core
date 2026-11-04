"""Reconcile the Taiga superuser flag with the administrator role group.

Env (from the hook):
    TAIGA_RBAC_ADMINISTRATORS  JSON list of ``{username, email, name}`` members
                               of the administrator role group
    TAIGA_RBAC_KEPT_SUPERUSERS JSON list of usernames that keep their flags even
                               outside the role group

Prints ``CHANGED promoted <username>`` or ``CHANGED demoted <username>`` per
account it changed, ``UNCHANGED`` when it wrote nothing.
"""

import json
import os

from django.contrib.auth import get_user_model


def _key(value):
    return str(value or "").strip().lower()


members = json.loads(os.environ["TAIGA_RBAC_ADMINISTRATORS"])
kept = {_key(name) for name in json.loads(os.environ["TAIGA_RBAC_KEPT_SUPERUSERS"])}
member_keys = {_key(member["username"]) for member in members} | {
    _key(member["email"]) for member in members
}
member_keys.discard("")

changed = False
for user in get_user_model().objects.order_by("id"):
    if getattr(user, "is_system", False):
        continue
    username = _key(user.username)
    is_member = username in member_keys or _key(user.email) in member_keys
    is_admin = bool(user.is_superuser and user.is_staff)
    if is_member and not is_admin:
        user.is_superuser = True
        user.is_staff = True
        user.save()
        print(f"CHANGED promoted {user.username}")
        changed = True
    elif (
        not is_member and username not in kept and (user.is_superuser or user.is_staff)
    ):
        user.is_superuser = False
        user.is_staff = False
        user.save()
        print(f"CHANGED demoted {user.username}")
        changed = True

if not changed:
    print("UNCHANGED")
