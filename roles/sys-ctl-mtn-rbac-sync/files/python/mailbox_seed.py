import json
import sys

from ldap_client import (
    SCOPE_ONE_LEVEL,
    SUCCESS,
    TYPE_OR_VALUE_EXISTS,
    present,
)
from ldap_mailbox import mailbox_address, sole_login

OBJECT_CLASS = "objectClass"


def mailbox_additions(dn, values, ldap, mailbox):
    """Return the values that seed an entry's mailbox, empty for an entry that holds a primary address.

    Args:
        dn: the DN of the entry.
        values: ``{lowercased attribute: [values]}`` of the entry.
        ldap: the ``ldap`` block of ``config.json``.
        mailbox: the content of ``mailbox.json``.

    Raises:
        ValueError: the entry holds no or several logins.
    """
    attributes = ldap["attributes"]
    if values.get(attributes["mail"].lower()):
        return {}
    login = sole_login(dn, values.get(attributes["id"].lower(), []), attributes["id"])
    additions = {}
    classes = {value.lower() for value in values.get(OBJECT_CLASS.lower(), [])}
    if mailbox["object_class"].lower() not in classes:
        additions[OBJECT_CLASS] = [mailbox["object_class"]]
    additions[attributes["mail"]] = [mailbox_address(login, mailbox["domain"])]
    return additions


def seed_mailboxes(connection, ldap, mailbox):
    """Give every account without a primary address its mailbox address; return whether all succeeded.

    Args:
        connection: an open ``ldap_client.Connection``, closed afterwards.
        ldap: the ``ldap`` block of ``config.json``.
        mailbox: the content of ``mailbox.json``.
    """
    attributes = ldap["attributes"]
    try:
        code = connection.bind(mailbox["bind_dn"], mailbox["bind_password"])
        if code != SUCCESS:
            print(f"[mailbox] FAILED bind answered result code {code}", file=sys.stderr)
            return False
        entries = connection.search(
            ldap["users_dn"],
            SCOPE_ONE_LEVEL,
            present(attributes["id"]),
            [attributes["id"], attributes["mail"], OBJECT_CLASS],
        )
        succeeded = True
        for dn, values in entries:
            try:
                additions = mailbox_additions(dn, values, ldap, mailbox)
            except ValueError as error:
                print(f"[mailbox] FAILED {error}", file=sys.stderr)
                succeeded = False
                continue
            if not additions:
                continue
            code = connection.add_values(dn, additions)
            address = additions[attributes["mail"]][0]
            if code == SUCCESS:
                print(f"[mailbox] CHANGED {dn} {attributes['mail']}={address}")
            elif code == TYPE_OR_VALUE_EXISTS:
                print(f"[mailbox] SKIPPED {dn} was seeded concurrently")
            else:
                print(
                    f"[mailbox] FAILED {dn} modify answered result code {code}",
                    file=sys.stderr,
                )
                succeeded = False
        return succeeded
    finally:
        connection.close()


def read_mailbox(path):
    """Return ``(mailbox, True)``, or ``(None, False)`` after one line saying why it is unreadable.

    Args:
        path: the ``mailbox.json`` the deploy wrote.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8")), True
    except (OSError, ValueError) as error:
        print(f"[mailbox] FAILED {type(error).__name__}: {error}", file=sys.stderr)
        return None, False
