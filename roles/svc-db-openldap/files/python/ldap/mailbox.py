"""Derive the mailbox address of a directory user, with the standard library only."""


def _rdn_value(dn, id_attribute):
    name, _, value = str(dn).split(",", 1)[0].partition("=")
    return value.lower() if name.strip().lower() == id_attribute.lower() else None


def sole_login(dn, logins, id_attribute):
    """Return the one login a user entry holds besides its RDN key.

    Args:
        dn: the DN of the entry.
        logins: the values of id_attribute the entry holds.
        id_attribute: the login attribute.

    Raises:
        ValueError: the entry holds no or several logins.
    """
    if len(logins) > 1:
        rdn = _rdn_value(dn, id_attribute)
        logins = [login for login in logins if str(login).lower() != rdn]
    if len(logins) > 1:
        raise ValueError(
            f"entry '{dn}' holds {len(logins)} values of {id_attribute}; "
            "its mailbox address needs exactly one."
        )
    if not logins or not logins[0]:
        raise ValueError(
            f"entry '{dn}' holds no {id_attribute}; its mailbox address needs one."
        )
    return str(logins[0])


def mailbox_address(login, mail_domain):
    """Return the mailbox address of a login.

    Args:
        login: the login of the user.
        mail_domain: domain of every mailbox address.
    """
    return f"{login}@{mail_domain}"
