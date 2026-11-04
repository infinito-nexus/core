import importlib.util

from ansible.errors import AnsibleFilterError
from ansible.module_utils.parsing.convert_bool import boolean

from plugins.filter.ldap.full_name import ldap_full_name
from utils import PROJECT_ROOT

_ENTRY_FIELDS = ("username", "firstname", "lastname", "uid", "gid")


# The RBAC sync timer imports this module on a node without Ansible, so it
# lives beside the LDAP client instead of under the importable utils/ tree.
def _load_mailbox_module():
    path = PROJECT_ROOT / "roles/svc-db-openldap/files/python/ldap/mailbox.py"
    spec = importlib.util.spec_from_file_location("svc_db_openldap_ldap_mailbox", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MAILBOX = _load_mailbox_module()


def _user_dn(key, id_attribute, users_dn):
    return f"{id_attribute}={key},{users_dn}"


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
            "dn": _user_dn(key, id_attribute, users_dn),
            "attributes": {
                "objectClass": list(structural),
                "uid": user["username"],
                "givenName": user["firstname"],
                "sn": user["lastname"],
                "cn": ldap_full_name(user, key),
                "loginShell": "/bin/bash",
                "homeDirectory": f"/home/{key}",
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
            "dn": _user_dn(key, id_attribute, users_dn),
            "attributes": {"objectClass": list(structural)},
        }
        for key in users
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


def _search_id(result, id_attribute):
    value = result.get(id_attribute)
    logins = value if isinstance(value, list) else [value] if value else []
    try:
        return _MAILBOX.sole_login(result.get("dn"), logins, id_attribute)
    except ValueError as error:
        raise AnsibleFilterError(str(error)) from error


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
    for key, user in users.items():
        dn = _user_dn(key, id_attribute, users_dn)
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
            "openldap_mailbox_entries": openldap_mailbox_entries,
            "openldap_secondary_mail_entries": openldap_secondary_mail_entries,
            "openldap_current_mail_secondary_entries": openldap_current_mail_secondary_entries,
            "openldap_user_passwords": openldap_user_passwords,
            "ldap_dn_entries": ldap_dn_entries,
        }
