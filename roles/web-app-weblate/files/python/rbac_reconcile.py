"""Converge Weblate's superuser flag and site teams on the directory role groups.

Environment:
    RBAC_MEMBERS: JSON ``{role: [{username, email, name}]}`` of the hook's roles.
    WEBLATE_RBAC_SUPERUSER_ROLE: role whose members are superusers.
    WEBLATE_RBAC_TEAMS: JSON ``{role: built-in site team name}``.
    WEBLATE_RBAC_PROTECTED: JSON list of usernames the run never changes.

Output:
    One ``CHANGED <username> <changes>`` line per changed account, else ``UNCHANGED``.
"""

import json
import os


def site_team(group_model, name):
    """Return the built-in site-wide team of that name.

    Args:
        group_model: ``weblate.auth.models.Group``.
        name: the team name.
    """
    return group_model.objects.get(
        name=name,
        internal=True,
        defining_project__isnull=True,
        defining_workspace__isnull=True,
    )


def converge(
    user_model, group_model, anonymous, members, superuser_role, teams, protected
):
    """Return one line per account whose flag or teams changed.

    Args:
        user_model: ``weblate.auth.models.User``.
        group_model: ``weblate.auth.models.Group``.
        anonymous: username of Weblate's anonymous account.
        members: ``{role: [members]}``.
        superuser_role: role whose members are superusers.
        teams: ``{role: team name}``.
        protected: usernames the run never changes.
    """
    superusers = {member["username"] for member in members[superuser_role]}
    targets = [
        (site_team(group_model, name), {member["username"] for member in members[role]})
        for role, name in sorted(teams.items())
    ]
    lines = []
    accounts = (
        user_model.objects.filter(is_bot=False)
        .exclude(username__in=[anonymous, *protected])
        .order_by("username")
    )
    for user in accounts:
        changes = []
        user.store_audit_state()
        wanted = user.username in superusers
        if user.is_superuser != wanted:
            user.is_superuser = wanted
            user.save(update_fields=["is_superuser"])
            changes.append(f"superuser={str(wanted).lower()}")
        current = set(user.groups.values_list("id", flat=True))
        for team, usernames in targets:
            belongs = user.username in usernames
            if belongs and team.id not in current:
                user.groups.add(team)
                changes.append(f"+{team.name}")
            elif not belongs and team.id in current:
                user.groups.remove(team)
                changes.append(f"-{team.name}")
        user.log_audit_state(None)
        if changes:
            lines.append(f"CHANGED {user.username} {' '.join(changes)}")
    return lines


def main(environ):
    """Converge every account and print the result.

    Args:
        environ: the process environment.
    """
    from django.conf import settings
    from weblate.auth.models import Group, User

    lines = converge(
        User,
        Group,
        settings.ANONYMOUS_USER_NAME,
        json.loads(environ["RBAC_MEMBERS"]),
        environ["WEBLATE_RBAC_SUPERUSER_ROLE"],
        json.loads(environ["WEBLATE_RBAC_TEAMS"]),
        json.loads(environ["WEBLATE_RBAC_PROTECTED"]),
    )
    print("\n".join(lines) if lines else "UNCHANGED")


main(os.environ)
