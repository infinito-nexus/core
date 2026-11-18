import frappe
from frappe.defaults import add_default, clear_default
from ldap3.utils.conv import escape_filter_chars

SETTINGS_KEY = "infinito_rbac"
GRANT_PARENT = "infinito_rbac_mapped_role"
ID_PARENT = "infinito_rbac_directory_id"
RECLAIM_PARENT = "infinito_rbac_directory_reclaim"
RECORD_PARENTS = (GRANT_PARENT, ID_PARENT, RECLAIM_PARENT)
CLAIMED_KEY = "infinito_rbac_claimed"


def group_cn(path):
    """Args:
        path: ``/<root>/<application>/<role>``, with or without its outer slashes.

    Returns:
        The ``cn`` of the LDAP group behind the role group path.

    Raises:
        ValueError: the path has not three segments.
    """
    segments = path.strip("/").split("/")
    if len(segments) != 3:
        raise ValueError(f"{path!r} is no group path /<root>/<application>/<role>")
    return f"{segments[1]}-{segments[2]}"


def linked_userids(user, providers):
    """Args:
        user: the ``User`` document.
        providers: the providers whose rows bind an account to a directory user.

    Returns:
        The lower-cased userids the account's ``User Social Login`` rows of the
        providers name.
    """
    return {
        row.userid.lower()
        for row in user.get("social_logins")
        if row.provider in providers and row.userid
    }


def protected_owners(mapping):
    """Args:
        mapping: ``ERPNEXT_RBAC_PROTECTED_OWNERS``, ``{protected user name:
            username}``.

    Returns:
        The mapping with the names in ``normal_address`` form and the usernames
        lower-cased.
    """
    return {
        normal_address(name): username.lower() for name, username in mapping.items()
    }


def owns_protected(user, username, providers, owners):
    """Args:
        user: a protected ``User`` document.
        username: a directory user's username.
        providers: the providers whose rows bind an account to a directory user.
        owners: ``protected_owners`` of ``ERPNEXT_RBAC_PROTECTED_OWNERS``.

    Returns:
        Whether a row of the providers on the account names the username or, on
        an account without such rows, ``owners`` names the username for it.
    """
    if not username:
        return False
    linked = linked_userids(user, providers)
    if linked:
        return username.lower() in linked
    return owners.get(normal_address(user.name)) == username.lower()


def bound_accounts(userid, providers):
    """Args:
        userid: the directory user's userid.
        providers: the providers whose rows bind an account to a directory user.

    Returns:
        The names of the accounts a ``User Social Login`` row of the providers binds
        to the userid.
    """
    return set(
        frappe.get_all(
            "User Social Login",
            filters={
                "provider": ["in", sorted(providers)],
                "parenttype": "User",
                "userid": userid,
            },
            pluck="parent",
        )
    )


def provision(email, username, provider):
    """Args:
        email: the member's e-mail, the account's name.
        username: the member's username, the userid of the account's link.
        provider: the provider of the ``User Social Login`` row that links it.

    Returns:
        The new enabled website account of the member, linked to it.
    """
    user = frappe.new_doc("User")
    user.email = email
    user.username = username
    user.first_name = username
    user.enabled = 1
    user.send_welcome_email = 0
    user.user_type = "Website User"
    user.new_password = frappe.generate_hash()
    user.append(
        "social_logins",
        {"provider": provider, "userid": username, "username": username},
    )
    user.flags.ignore_permissions = True
    user.flags.no_welcome_mail = True
    user.insert()
    return user


def ensure_roles(roles):
    """Args:
        roles: the ERPNext roles about to be granted or mapped.

    Returns:
        One line per role the site lacked and got as an empty Role.
    """
    lines = []
    for role in sorted(roles):
        if not frappe.db.exists("Role", role):
            doc = frappe.get_doc({"doctype": "Role", "role_name": role})
            doc.flags.ignore_permissions = True
            doc.insert()
            lines.append(f"CHANGED created role {role}")
    return lines


def _records(parent, name):
    return set(
        frappe.get_all(
            "DefaultValue",
            filters={"parent": parent, "defkey": name},
            pluck="defvalue",
        )
    )


def mapped_grants(name):
    """Args:
        name: the account's name.

    Returns:
        The roles of ``services.erpnext.group_roles`` the mapping granted the account.
    """
    return _records(GRANT_PARENT, name)


def recorded_ids(name):
    """Args:
        name: the account's name.

    Returns:
        The directory ids recorded with the account.
    """
    return _records(ID_PARENT, name)


def record_id(name, uuid):
    """Args:
    name: the account's name.
    uuid: the ``entryUUID`` of its directory entry.
    """
    add_default(name, uuid, ID_PARENT)


def identified_accounts(uuid):
    """Args:
        uuid: the ``entryUUID`` of a directory entry.

    Returns:
        The names of the accounts that carry the directory id among their records.
    """
    return set(
        frappe.get_all(
            "DefaultValue",
            filters={"parent": ID_PARENT, "defvalue": uuid},
            pluck="defkey",
        )
    ) - {CLAIMED_KEY}


def reclaim_requested(name):
    """Args:
        name: the account's name.

    Returns:
        Whether a reclaim request is pending for the account.
    """
    return bool(_records(RECLAIM_PARENT, name))


def reclaim_id(name, uuid):
    """Args:
    name: the account's name.
    uuid: the ``entryUUID`` that replaces its recorded directory ids.
    """
    clear_default(key=name, parent=ID_PARENT)
    add_default(name, uuid, ID_PARENT)
    drop_reclaim(name)


def reclaim_requests():
    """Returns:
    The names of the accounts a reclaim request is pending for.
    """
    return set(
        frappe.get_all(
            "DefaultValue", filters={"parent": RECLAIM_PARENT}, pluck="defkey"
        )
    )


def drop_reclaim(name):
    """Args:
    name: the account's name.
    """
    clear_default(key=name, parent=RECLAIM_PARENT)


def normal_address(address):
    """Args:
        address: an e-mail address as a directory or a sign-in spells it.

    Returns:
        The address stripped, its inner whitespace runs collapsed to one space as
        the directory's insignificant-space matching does, and lower-cased: the
        form every holder count compares.
    """
    return " ".join(address.split()).lower()


def ambiguous_holders(holders):
    """Args:
        holders: ``(usernames, uuid)`` of every entry that holds one address.

    Returns:
        Whether those entries are more than one directory entry.
    """
    return (
        len(
            {
                (frozenset(name.lower() for name in usernames), uuid)
                for usernames, uuid in holders
            }
        )
        > 1
    )


def directory_holders(ldap, username, email, attribute):
    """Args:
        ldap: the site's ``LDAP Settings``.
        username: a directory user's username.
        email: an address in ``normal_address`` form.
        attribute: the attribute that holds an entry's immutable id.

    Returns:
        ``(usernames, uuid, addresses)`` of every entry under the user search path
        that holds the username or the address, names lower-cased and addresses in
        ``normal_address`` form.
    """
    user_field = ldap.ldap_username_field
    mail_field = ldap.ldap_email_field
    connection = ldap.connect_to_ldap(
        ldap.base_dn, ldap.get_password(raise_exception=False)
    )
    try:
        connection.search(
            search_base=ldap.ldap_search_path_user,
            search_filter=(
                f"(|({user_field}={escape_filter_chars(username)})"
                f"({mail_field}={escape_filter_chars(email)}))"
            ),
            attributes=[user_field, mail_field, attribute],
        )
        entries = list(connection.entries)
    finally:
        try:
            connection.unbind()
        except Exception as error:
            frappe.logger(SETTINGS_KEY).error(
                "the directory connection could not be closed: %s", error
            )
    found = []
    for entry in entries:
        values = {
            name.lower(): [str(value) for value in items]
            for name, items in entry.entry_attributes_as_dict.items()
        }
        found.append(
            (
                {value.lower() for value in values.get(user_field.lower(), [])},
                next(iter(values.get(attribute.lower(), [])), ""),
                {normal_address(value) for value in values.get(mail_field.lower(), [])},
            )
        )
    return found


def ids_claimed():
    """Returns:
    Whether the claim epoch marker is recorded.
    """
    return bool(_records(ID_PARENT, CLAIMED_KEY))


def mark_ids_claimed():
    add_default(CLAIMED_KEY, "1", ID_PARENT)


def rebind(user, username, providers):
    """Args:
        user: the ``User`` document, whose recorded directory id names the entry.
        username: the entry's current username.
        providers: the providers whose rows bind an account to a directory user.

    Returns:
        One line per account whose rows of the providers now name the username.
    """
    rows = [
        row
        for row in user.get("social_logins")
        if row.provider in providers
        and row.userid
        and row.userid.lower() != username.lower()
    ]
    for row in rows:
        row.userid = username
        row.username = username
    if not rows:
        return []
    user.flags.ignore_permissions = True
    user.save()
    return [f"CHANGED {user.name} rebound to {username}"]


def move_records(old, new):
    """Args:
    old: the account's former name.
    new: the account's new name.
    """
    for parent in RECORD_PARENTS:
        for value in sorted(_records(parent, old) - _records(parent, new)):
            add_default(new, value, parent)
        clear_default(key=old, parent=parent)


def carry_records(doc, method, old, new, merge=False):
    """Args:
    doc: the renamed ``User`` document.
    method: the document event, ``after_rename``.
    old: the account's former name.
    new: the account's new name.
    merge: whether the rename merged into an existing account.
    """
    move_records(old, new)


def drop_records(doc, method=None):
    """Args:
    doc: the deleted ``User`` document.
    method: the document event, ``on_trash``.
    """
    for parent in RECORD_PARENTS:
        clear_default(key=doc.name, parent=parent)


def converge_mapped(user, wanted):
    """Args:
        user: the ``User`` document, saved by ``add_roles`` and ``remove_roles``.
        wanted: the mapped roles the account's groups grant it.

    Returns:
        One ``CHANGED`` line per role created, granted or revoked.
    """
    lines = []
    granted = mapped_grants(user.name)
    current = {row.role for row in user.get("roles")}
    missing = wanted - current
    stale = (granted & current) - wanted
    if missing:
        lines.extend(ensure_roles(missing))
        user.add_roles(*sorted(missing))
        for role in sorted(missing - granted):
            add_default(user.name, role, GRANT_PARENT)
        lines.extend(f"CHANGED {user.name} granted {role}" for role in sorted(missing))
    if stale:
        user.remove_roles(*sorted(stale))
        lines.extend(f"CHANGED {user.name} revoked {role}" for role in sorted(stale))
    for role in sorted((granted - current - missing) | stale):
        clear_default(key=user.name, value=role, parent=GRANT_PARENT)
    return lines
