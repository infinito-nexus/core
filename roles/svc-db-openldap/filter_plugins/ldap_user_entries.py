def _user_dn(key, id_attribute, users_dn):
    return f"{id_attribute}={key},{users_dn}"


def openldap_user_entries(users, id_attribute, users_dn, structural):
    """Return the ldap_entries entries that create the inventory users.

    Args:
        users: mapping of user key to user record, as lookup('users_non_reserved').
        id_attribute: RDN attribute of a user entry.
        users_dn: DN of the users OU.
        structural: structural object classes of a user entry.
    """
    return [
        {
            "dn": _user_dn(key, id_attribute, users_dn),
            "attributes": {
                "objectClass": list(structural),
                "uid": user["username"],
                "givenName": user["firstname"],
                "sn": user["lastname"],
                "cn": user.get("cn", key),
                "loginShell": "/bin/bash",
                "homeDirectory": f"/home/{key}",
                "uidNumber": str(int(user["uid"])),
                "gidNumber": str(int(user["gid"])),
            },
        }
        for key, user in users.items()
    ]


def openldap_user_mail_entries(users, id_attribute, users_dn, structural):
    """Return the ldap_entries entries that keep object classes and mail current.

    Args:
        users: mapping of user key to user record, as lookup('users_non_reserved').
        id_attribute: RDN attribute of a user entry.
        users_dn: DN of the users OU.
        structural: structural object classes of a user entry.
    """
    return [
        {
            "dn": _user_dn(key, id_attribute, users_dn),
            "attributes": {"objectClass": list(structural), "mail": user["email"]},
        }
        for key, user in users.items()
    ]


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
            "openldap_user_mail_entries": openldap_user_mail_entries,
            "ldap_dn_entries": ldap_dn_entries,
        }
