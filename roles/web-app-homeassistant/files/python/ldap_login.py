"""Sign a Home Assistant user in against the directory and name their group.

Args:
    --uri: ``ldap://`` or ``ldaps://`` URI of the directory.
    --users-dn: DN the login name is searched under, one level deep.
    --login-attribute: attribute that holds the login name.
    --display-attribute: attribute printed as the display name when present.
    --name-part-attribute: attributes joined into the display name otherwise, repeatable.
    --admin-group: DN of the role group whose members become ``system-admin``.
    --user-group: DN of the role group whose members become ``system-users``.

Output:
    ``name = ...`` and ``group = ...`` on standard output and exit code 0 for a
    member of either group; exit code 1 for anyone else and on every directory error.
"""

import argparse
import os
import sys

from ldap_client import (
    SCOPE_BASE,
    SCOPE_ONE_LEVEL,
    SUCCESS,
    Connection,
    DirectoryError,
    equality,
    normalize_dn,
    present,
)

MEMBERSHIP_ATTRIBUTE = "memberOf"
PRESENCE_ATTRIBUTE = "objectClass"
ADMIN_GROUP_ID = "system-admin"
USER_GROUP_ID = "system-users"


def group_for(member_of, admin_group, user_group):
    """Return the Home Assistant group a directory account belongs in, or None.

    Args:
        member_of: the DNs of the groups the account is a member of.
        admin_group: DN of the administrator role group.
        user_group: DN of the user role group.
    """
    groups = {normalize_dn(dn) for dn in member_of}
    if normalize_dn(admin_group) in groups:
        return ADMIN_GROUP_ID
    if normalize_dn(user_group) in groups:
        return USER_GROUP_ID
    return None


def display_name(values, options, username):
    """Return the single-line display name of an account.

    Args:
        values: the attributes of the account, keyed by lowercased name.
        options: the parsed arguments.
        username: the login name, shown when the directory holds no name.
    """
    shown = values.get(options.display_attribute.lower())
    if not shown:
        parts = [
            values[attribute.lower()][0]
            for attribute in options.name_part_attribute
            if values.get(attribute.lower())
        ]
        shown = [" ".join(parts)] if parts else [username]
    return " ".join(shown[0].split())


def authenticate(connection, options, username, password):
    """Return ``(display name, group)`` for a valid member, or None.

    The typed login name must equal a stored value exactly, so differently
    cased spellings of one account cannot open separate Home Assistant users.

    Args:
        connection: an open ``Connection``.
        options: the parsed arguments.
        username: the login name Home Assistant received.
        password: the password Home Assistant received.
    """
    if not username or not password:
        return None
    login_key = options.login_attribute.lower()
    found = connection.search(
        options.users_dn,
        SCOPE_ONE_LEVEL,
        equality(options.login_attribute, username),
        [options.login_attribute],
    )
    if len(found) != 1 or username not in found[0][1].get(login_key, []):
        return None
    dn = found[0][0]
    if connection.bind(dn, password) != SUCCESS:
        return None
    attributes = [
        MEMBERSHIP_ATTRIBUTE,
        options.display_attribute,
        *options.name_part_attribute,
    ]
    entries = connection.search(dn, SCOPE_BASE, present(PRESENCE_ATTRIBUTE), attributes)
    if len(entries) != 1:
        return None
    values = entries[0][1]
    group = group_for(
        values.get(MEMBERSHIP_ATTRIBUTE.lower(), []),
        options.admin_group,
        options.user_group,
    )
    if group is None:
        return None
    return display_name(values, options, username), group


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--uri", required=True)
    parser.add_argument("--users-dn", required=True)
    parser.add_argument("--login-attribute", required=True)
    parser.add_argument("--display-attribute", required=True)
    parser.add_argument("--name-part-attribute", action="append", required=True)
    parser.add_argument("--admin-group", required=True)
    parser.add_argument("--user-group", required=True)
    return parser.parse_args(argv)


def main(argv, environ):
    """Run one sign-in and return the exit code.

    Args:
        argv: the command line arguments.
        environ: the environment Home Assistant passes.
    """
    options = parse_arguments(argv)
    try:
        username = environ["username"]
        connection = Connection(options.uri)
        try:
            result = authenticate(connection, options, username, environ["password"])
        finally:
            connection.close()
    except (DirectoryError, OSError, KeyError, IndexError, ValueError) as error:
        print(
            f"directory sign-in failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    if result is None:
        print(
            f"directory sign-in refused {username!r}: wrong credentials or no Home Assistant role",
            file=sys.stderr,
        )
        return 1
    name, group = result
    print(f"name = {name}")
    print(f"group = {group}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], os.environ))
