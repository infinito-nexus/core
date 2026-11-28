import importlib.util

from ansible.errors import AnsibleFilterError
from ansible.module_utils.parsing.convert_bool import boolean

from plugins.filter.ldap.full_name import ldap_full_name
from plugins.filter.ldap.user_dn import ldap_user_dn
from utils import PROJECT_ROOT

_ENTRY_FIELDS = ("username", "firstname", "lastname", "uid", "gid")
_HOME_ATTRIBUTE = "homeDirectory"


def _home_directory(name):
    return f"/home/{name}"


# The RBAC sync timer imports this module on a node without Ansible, so it
# lives beside the LDAP client instead of under the importable utils/ tree.
def _load_ldap_module(name):
    path = PROJECT_ROOT / f"roles/svc-db-openldap/files/python/ldap/{name}.py"
    spec = importlib.util.spec_from_file_location(f"svc_db_openldap_ldap_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MAILBOX = _load_ldap_module("mailbox")
_CLIENT = _load_ldap_module("client")


def _require_entry_fields(users):
    for key, user in users.items():
        missing = [field for field in _ENTRY_FIELDS if field not in user]
        if missing:
            raise AnsibleFilterError(
                f"user '{key}' lacks {', '.join(missing)}. A user key that no "
                "role's meta/users.yml declares gets none of these derived, so its "
                "inventory entry must carry the full record or be removed."
            )


def openldap_user_entries(users, id_attribute, users_dn, structural):
    """Return the ldap_entries entries that create the inventory users.

    Args:
        users: mapping of user key to user record, as lookup('users_non_reserved').
        id_attribute: RDN attribute of a user entry.
        users_dn: DN of the users OU.
        structural: structural object classes of a user entry.

    Raises:
        AnsibleFilterError: a record lacks a field the entry is built from.
    """
    _require_entry_fields(users)
    return [
        {
            "dn": ldap_user_dn(user, id_attribute, users_dn),
            "attributes": {
                "objectClass": list(structural),
                "uid": user["username"],
                "givenName": user["firstname"],
                "sn": user["lastname"],
                "cn": ldap_full_name(user, key),
                "loginShell": "/bin/bash",
                _HOME_ATTRIBUTE: _home_directory(key),
                "uidNumber": str(int(user["uid"])),
                "gidNumber": str(int(user["gid"])),
            },
        }
        for key, user in users.items()
    ]


def openldap_user_class_entries(users, id_attribute, users_dn, structural):
    """Return the ldap_entries entries that keep the object classes current.

    Args:
        users: mapping of user key to user record, as lookup('users_non_reserved').
        id_attribute: RDN attribute of a user entry.
        users_dn: DN of the users OU.
        structural: structural object classes of a user entry.
    """
    return [
        {
            "dn": ldap_user_dn(user, id_attribute, users_dn),
            "attributes": {"objectClass": list(structural)},
        }
        for user in users.values()
    ]


def openldap_user_mail_entries(users, id_attribute, users_dn, structural):
    """Return the ldap_entries entries that keep object classes and mail current.

    Args:
        users: mapping of user key to user record, as lookup('users_non_reserved').
        id_attribute: RDN attribute of a user entry.
        users_dn: DN of the users OU.
        structural: structural object classes of a user entry.
    """
    entries = openldap_user_class_entries(users, id_attribute, users_dn, structural)
    for entry, user in zip(entries, users.values(), strict=True):
        entry["attributes"]["mail"] = user["email"]
    return entries


def openldap_user_login_entries(users, id_attribute, users_dn):
    """Args:
        users: mapping of user key to user record, as lookup('users_non_reserved').
        id_attribute: RDN and login attribute of a user entry.
        users_dn: DN of the users OU.

    Returns:
        One ldap_entries entry per user whose id_attribute holds only its username.
    """
    return [
        {
            "dn": ldap_user_dn(user, id_attribute, users_dn),
            "attributes": {id_attribute: user["username"]},
        }
        for user in users.values()
    ]


def _search_id(result, id_attribute):
    value = result.get(id_attribute)
    logins = value if isinstance(value, list) else [value] if value else []
    try:
        return _MAILBOX.sole_login(result.get("dn"), logins, id_attribute)
    except ValueError as error:
        raise AnsibleFilterError(str(error)) from error


def _values(result, attribute):
    value = next(
        (held for name, held in result.items() if name.lower() == attribute.lower()),
        None,
    )
    return value if isinstance(value, list) else [value] if value else []


def _references(groups, attributes, old, new, same):
    return [
        {"dn": group["dn"], "attribute": attribute, "old": value, "new": new}
        for group in groups
        for attribute in attributes
        for value in _values(group, attribute)
        if same(str(value), old)
    ]


def _same_dn(value, dn):
    return _CLIENT.normalize_dn(value) == _CLIENT.normalize_dn(dn)


def _same_login(value, login):
    return value == login


def _created_here(entry, id_attribute, structural):
    classes = {str(value).lower() for value in _values(entry, "objectClass")}
    homes = {_home_directory(value) for value in _values(entry, id_attribute)}
    return {name.lower() for name in structural} <= classes and bool(
        homes & {str(value) for value in _values(entry, _HOME_ATTRIBUTE)}
    )


def openldap_user_renames(
    users,
    entries,
    groups,
    id_attribute,
    users_dn,
    structural,
    dn_attributes,
    login_attributes,
):
    """Args:
        users: mapping of user key to user record, as lookup('users_non_reserved').
        entries: ldap_search results of the user entries, each with dn,
            id_attribute, objectClass and homeDirectory.
        groups: ldap_search results of the groups, each with dn and its member attributes.
        id_attribute: RDN and login attribute of a user entry.
        users_dn: DN of the users OU.
        structural: structural object classes every entry this role creates holds.
        dn_attributes: group attributes that hold member DNs.
        login_attributes: group attributes that hold member logins.

    Returns:
        One {dn, new_rdn, move, references} per user whose key differs from
        its username, when this role's entry still sits at the key-named DN
        (move) or, once the username-named entry exists, a group still holds
        that DN or the key; references lists one {dn, attribute, old, new} per
        such group value. [] once the directory is clean. This role created an
        entry when it holds every structural class and a homeDirectory naming
        one of its id_attribute values.

    Raises:
        AnsibleFilterError: the key-named DN holds an entry this role did not
            create, holds this role's entry while the key is another user's
            username, or the username-named DN already holds an entry too.
    """
    held = {_CLIENT.normalize_dn(entry["dn"]): entry for entry in entries}
    named = {
        _CLIENT.normalize_dn(ldap_user_dn(user, id_attribute, users_dn))
        for user in users.values()
    }
    renames = []
    for key, user in users.items():
        login = user["username"]
        if key.lower() == login.lower():
            continue
        old_dn = f"{id_attribute}={key},{users_dn}"
        new_dn = ldap_user_dn(user, id_attribute, users_dn)
        entry = held.get(_CLIENT.normalize_dn(old_dn))
        own = entry is not None and _created_here(entry, id_attribute, structural)
        if _CLIENT.normalize_dn(old_dn) in named:
            if own:
                raise AnsibleFilterError(
                    f"user '{key}' is the username of another user, so its old "
                    f"entry '{old_dn}' cannot move on its own; move it by hand."
                )
            continue
        if entry is not None and not own:
            raise AnsibleFilterError(
                f"entry '{old_dn}' of user '{key}' lacks the object classes or "
                "the home directory this role writes; it is no entry this role "
                "created, so check it by hand."
            )
        if entry is not None and _CLIENT.normalize_dn(new_dn) in held:
            raise AnsibleFilterError(
                f"user '{key}' has an entry at both '{old_dn}' and '{new_dn}'; "
                "merge them by hand."
            )
        if entry is None and _CLIENT.normalize_dn(new_dn) not in held:
            continue
        references = _references(
            groups, dn_attributes, old_dn, new_dn, _same_dn
        ) + _references(groups, login_attributes, key, login, _same_login)
        if entry is not None or references:
            renames.append(
                {
                    "dn": entry["dn"] if entry is not None else old_dn,
                    "new_rdn": f"{id_attribute}={login}",
                    "move": entry is not None,
                    "references": references,
                }
            )
    return renames


def _in_domain(address, mail_domain):
    return str(address).lower().endswith("@" + str(mail_domain).lower())


def openldap_mailbox_entries(results, id_attribute, mail_attribute, mail_domain):
    """Return the ldap_entries entries that set every primary address to its mailbox.

    Args:
        results: ldap_search results of the user entries, each with dn and id_attribute.
        id_attribute: login attribute the mailbox address is built from.
        mail_attribute: attribute holding the primary address.
        mail_domain: domain of every mailbox address.

    Raises:
        AnsibleFilterError: an entry holds no or several values of id_attribute.
    """
    return [
        {
            "dn": result["dn"],
            "attributes": {
                mail_attribute: _MAILBOX.mailbox_address(
                    _search_id(result, id_attribute), mail_domain
                )
            },
        }
        for result in results
    ]


def openldap_secondary_mail_entries(
    results, addresses, id_attribute, secondary_attribute, mail_domain
):
    """Return the ldap_entries entries that seed the secondary addresses.

    Args:
        results: ldap_search results of the user entries, each with dn and id_attribute.
        addresses: mapping of login to the address that becomes the secondary one.
        id_attribute: login attribute the addresses are keyed by.
        secondary_attribute: attribute holding the secondary address.
        mail_domain: domain of every mailbox address; an address inside it is skipped,
            since the user profile refuses it as secondary address.
    """
    entries = []
    for result in results:
        address = addresses.get(_search_id(result, id_attribute))
        if address and not _in_domain(address, mail_domain):
            entries.append(
                {"dn": result["dn"], "attributes": {secondary_attribute: address}}
            )
    return entries


def openldap_current_mail_secondary_entries(
    results, mail_attribute, secondary_attribute, mail_domain
):
    """Return the ldap_entries entries that keep each entry's current address as its secondary one.

    Args:
        results: ldap_search results of the user entries, each with dn and mail_attribute.
        mail_attribute: attribute holding the primary address before the mailbox layout.
        secondary_attribute: attribute holding the secondary address.
        mail_domain: domain of every mailbox address; an address inside it is skipped,
            since the user profile refuses it as secondary address.

    Returns:
        One entry per result whose mail_attribute holds an address outside
        mail_domain, carrying the first such address.
    """
    entries = []
    for result in results:
        value = result.get(mail_attribute)
        addresses = value if isinstance(value, list) else [value] if value else []
        kept = [
            address
            for address in addresses
            if address and not _in_domain(address, mail_domain)
        ]
        if kept:
            entries.append(
                {"dn": result["dn"], "attributes": {secondary_attribute: kept[0]}}
            )
    return entries


def openldap_user_passwords(users, id_attribute, users_dn, created_dns):
    """Return the ldap_passwords entries of the users whose password is managed.

    Args:
        users: mapping of user key to user record, as lookup('users_non_reserved').
        id_attribute: RDN attribute of a user entry.
        users_dn: DN of the users OU.
        created_dns: DNs this run created; such a user gets its password even
            when its record sets password_update to false.
    """
    created = set(created_dns)
    entries = []
    for user in users.values():
        dn = ldap_user_dn(user, id_attribute, users_dn)
        if boolean(user.get("password_update", True), strict=False) or dn in created:
            entries.append({"dn": dn, "passwd": user["password"]})
    return entries


def ldap_dn_entries(dns, attributes):
    """Return one ldap_entries entry per DN, all with the same attributes.

    Args:
        dns: the DNs.
        attributes: mapping of attribute name to value or values.
    """
    return [{"dn": dn, "attributes": dict(attributes)} for dn in dns]


class FilterModule:
    def filters(self):
        return {
            "openldap_user_entries": openldap_user_entries,
            "openldap_user_class_entries": openldap_user_class_entries,
            "openldap_user_mail_entries": openldap_user_mail_entries,
            "openldap_user_login_entries": openldap_user_login_entries,
            "openldap_user_renames": openldap_user_renames,
            "openldap_mailbox_entries": openldap_mailbox_entries,
            "openldap_secondary_mail_entries": openldap_secondary_mail_entries,
            "openldap_current_mail_secondary_entries": openldap_current_mail_secondary_entries,
            "openldap_user_passwords": openldap_user_passwords,
            "ldap_dn_entries": ldap_dn_entries,
        }
