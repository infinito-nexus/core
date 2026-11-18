"""Site config ``infinito_rbac`` (written by ``files/python/apply/login/rbac.py``):
groups_claim: userinfo claim with the full paths of the user's groups.
username_claim: userinfo claim with the username of a new account.
given_name_claim: userinfo claim with the first name.
family_name_claim: userinfo claim with the last name.
role_grants: ``{group path: [ERPNext role, ...]}`` of the role groups of this
    role.
group_roles: ``{group path: [ERPNext role, ...]}`` of
    ``services.erpnext.group_roles``.
protected_users: user names a sign-in never changes.
protected_owners: ``ERPNEXT_RBAC_PROTECTED_OWNERS``, ``{protected user name:
    username}`` of the protected accounts their directory user reaches without a
    ``User Social Login`` row.
directory_provider: provider of the ``User Social Login`` row the RBAC hook
    writes on every member it provisions or adopts.
uuid_attribute: the directory attribute that holds an entry's immutable id.
directory_ids: whether sign-ins read and check that id.
"""

import frappe
from frappe.integrations.doctype.ldap_settings.ldap_settings import LDAPSettings
from frappe.integrations.oauth2_logins import custom as upstream_custom
from frappe.integrations.oauth2_logins import decoder_compat
from frappe.utils.oauth import get_email, get_info_via_oauth, login_oauth_user

from infinito_rbac.guard import (
    PROVIDER,
    account_refusal,
    binding_providers,
    grants_of,
    group_path,
    is_protected,
    shared_refusal,
)
from infinito_rbac.roles import (
    SETTINGS_KEY,
    ambiguous_holders,
    converge_mapped,
    directory_holders,
    ensure_roles,
    group_cn,
    linked_userids,
    mapped_grants,
    normal_address,
    provision,
    rebind,
    record_id,
    recorded_ids,
)


def directory_entry(ldap, username, email):
    """Args:
        ldap: the site's ``LDAP Settings``.
        username: the directory user's userid.
        email: the address the sign-in lands on, in ``normal_address`` form.

    Returns:
        ``(uuid, shared)``: the ``entryUUID`` of the one entry with the username,
        "" when not exactly one entry holds it and None while ``directory_ids`` is
        off, and whether more than one entry holds the address.

    Raises:
        frappe.PermissionError: the directory could not be searched.
    """
    settings = frappe.conf[SETTINGS_KEY]
    if not settings["directory_ids"]:
        return None, False
    if not all(isinstance(value, str) and value for value in (username, email)):
        return "", False
    try:
        found = directory_holders(ldap, username, email, settings["uuid_attribute"])
    except Exception as error:
        frappe.clear_messages()
        frappe.logger(SETTINGS_KEY).error(
            "REFUSED sign-in of %s: the directory could not be searched: %s",
            username,
            error,
        )
        frappe.throw(
            "Sign-in refused: the directory could not be searched.",
            frappe.PermissionError,
        )
    ids = [uuid for names, uuid, _ in found if username.lower() in names]
    shared = [(names, uuid) for names, uuid, addresses in found if email in addresses]
    return (ids[0] if len(ids) == 1 else ""), ambiguous_holders(shared)


def refusal(info, userid_claim, settings):
    """Args:
        info: the userinfo of the sign-in.
        userid_claim: the claim Frappe stores as the userid of an account's ``keycloak`` row.
        settings: the ``infinito_rbac`` site config.

    Returns:
        ``(reason, uuid)``: why the Keycloak sign-in may not land on its account,
        None when it may, and the directory id of its user.
    """
    if info.get("email_verified") is not True:
        return "the e-mail address of the Keycloak account is not verified", ""
    email = get_email(info)
    if not isinstance(email, str) or not email.strip():
        return "the Keycloak account has no e-mail address", ""
    userid = info.get(userid_claim)
    if not isinstance(userid, str) or not userid:
        return f"the sign-in carries no {userid_claim} claim", ""
    name = normal_address(email)
    uuid, shared = directory_entry(frappe.get_single("LDAP Settings"), userid, name)
    reason = shared_refusal(shared, name, userid, uuid, settings)
    if reason is not None:
        return reason, uuid
    reason = account_refusal(
        name, userid, info.get(settings["groups_claim"]), settings, uuid
    )
    return reason, uuid


def set_enabled(user, enabled):
    """Args:
    user: the ``User`` document.
    enabled: 1 or 0.
    """
    user.enabled = enabled
    user.save()


def refresh_profile(user, info, settings):
    """Args:
        user: the ``User`` document.
        info: the userinfo of the sign-in.
        settings: the ``infinito_rbac`` site config.

    Returns:
        One line per name field copied from the sign-in.
    """
    changed = []
    for field, claim in (
        ("first_name", settings["given_name_claim"]),
        ("last_name", settings["family_name_claim"]),
    ):
        value = info.get(claim)
        if isinstance(value, str) and value.strip() and value != user.get(field):
            setattr(user, field, value)
            changed.append(field)
    if changed:
        user.save()
    return [f"CHANGED {user.name} updated {field}" for field in changed]


def converge(info, settings, uuid):
    """Args:
        info: the userinfo of the sign-in.
        settings: the ``infinito_rbac`` site config.
        uuid: the ``entryUUID`` of the directory user, recorded with a member's
            account that carries none; None while ``directory_ids`` is off.

    Returns:
        One line per change the role groups of the sign-in make to its account.
    """
    email = get_email(info)
    if not email:
        return []
    email = normal_address(email)
    if is_protected(email, settings):
        return []
    claim = settings["groups_claim"]
    if claim not in info:
        frappe.throw(f"The sign-in of {email} carries no {claim} claim")

    groups = {group_path(group) for group in info[claim]}
    grants = grants_of(settings["role_grants"])
    mapped = grants_of(settings["group_roles"])
    managed = set().union(*grants.values())
    held = [group for group in grants if group in groups]
    wanted = set().union(*(grants[group] for group in held))
    wanted_mapped = set().union(*(mapped[group] for group in mapped if group in groups))
    member = bool(held or wanted_mapped)

    lines = []
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
    elif member:
        user = provision(
            email, info[settings["username_claim"]], settings["directory_provider"]
        )
        lines.append(f"CHANGED {email} created")
    else:
        return lines
    user.flags.ignore_permissions = True
    if not held and not linked_userids(user, binding_providers(settings)):
        return lines

    if member and not user.enabled:
        set_enabled(user, 1)
        lines.append(f"CHANGED {email} enabled")
    if member and uuid and not recorded_ids(email):
        record_id(email, uuid)
        lines.append(f"CHANGED {email} recorded its directory id")
    if member and uuid and recorded_ids(email) == {uuid}:
        lines.extend(
            rebind(user, info[settings["username_claim"]], binding_providers(settings))
        )
    if member:
        lines.extend(refresh_profile(user, info, settings))

    current = {row.role for row in user.get("roles")}
    recorded = mapped_grants(email)
    missing = wanted - current
    surplus = (current & managed) - wanted
    if missing:
        lines.extend(ensure_roles(missing))
        user.add_roles(*sorted(missing))
        lines.extend(f"CHANGED {email} granted {role}" for role in sorted(missing))
    if surplus:
        user.remove_roles(*sorted(surplus))
        lines.extend(f"CHANGED {email} revoked {role}" for role in sorted(surplus))
    lines.extend(converge_mapped(user, wanted_mapped))

    if not member and user.enabled and not current - managed - recorded:
        set_enabled(user, 0)
        lines.append(f"CHANGED {email} disabled")
    return lines


def guarded_login(code, state):
    """Args:
        code: the authorization code Keycloak returned.
        state: the login attempt Frappe issued.

    Raises:
        frappe.PermissionError: ``refusal`` found a reason against the sign-in.
    """
    settings = frappe.conf[SETTINGS_KEY]
    userid_claim = frappe.db.get_value("Social Login Key", PROVIDER, "user_id_property")
    if not userid_claim:
        frappe.throw(
            f"Keycloak sign-in refused: the Social Login Key {PROVIDER} names no user_id_property.",
            frappe.PermissionError,
        )
    info = get_info_via_oauth(PROVIDER, code, decoder=decoder_compat)
    reason, uuid = refusal(info, userid_claim, settings)
    logger = frappe.logger(SETTINGS_KEY)
    if reason is not None:
        logger.warning(
            "REFUSED Keycloak sign-in of %s as %s: %s",
            info.get(userid_claim),
            get_email(info),
            reason,
        )
        frappe.throw(f"Keycloak sign-in refused: {reason}.", frappe.PermissionError)
    for line in converge(info, settings, uuid):
        logger.info(line)
    frappe.db.commit()
    login_oauth_user(info, provider=PROVIDER, state=state)


@frappe.whitelist(allow_guest=True)
def login_via_keycloak(code: str, state: str):
    """Args:
    code: the authorization code Keycloak returned.
    state: the login attempt Frappe issued.
    """
    guarded_login(code, state)


@frappe.whitelist(allow_guest=True)
def custom(code: str, state: str):
    """Args:
    code: the authorization code the provider returned.
    state: the login attempt Frappe issued.
    """
    path = frappe.request.path[1:].split("/")
    if len(path) == 4 and path[3].strip().lower() == PROVIDER:
        guarded_login(code, state)
        return
    upstream_custom(code, state)


@frappe.whitelist()
def refuse_default_write(key, value, parent=None):
    """Args:
        key: the default's key.
        value: the default's value.
        parent: the default's parent.

    Raises:
        frappe.PermissionError: on every call.
    """
    frappe.throw(
        "frappe.client.set_default is disabled on this site", frappe.PermissionError
    )


def first_value(value):
    """Args:
        value: an attribute of ``convert_ldap_entry_to_dict``, a list for a
            multi-valued one.

    Returns:
        The first value of a list, as Keycloak's LDAP federation and the RBAC sync
        read it, "" for an empty one, else the value itself.
    """
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def ldap_info(user_data, groups, settings):
    """Args:
        user_data: ``LDAPSettings.convert_ldap_entry_to_dict`` of the entry.
        groups: the ``cn`` of every directory group that holds the entry, or None.
        settings: the ``infinito_rbac`` site config.

    Returns:
        The userinfo a Keycloak sign-in of the directory entry would carry.
    """
    paths = {
        group_cn(path).lower(): path
        for mapping in (settings["role_grants"], settings["group_roles"])
        for path in grants_of(mapping)
    }
    held = {str(cn).lower() for cn in groups or ()}
    email = user_data["email"]
    return {
        "email": normal_address(email) if isinstance(email, str) else email,
        settings["groups_claim"]: sorted(paths[cn] for cn in held if cn in paths),
        settings["username_claim"]: user_data["username"],
        settings["given_name_claim"]: user_data["first_name"],
        settings["family_name_claim"]: user_data["last_name"],
    }


def ldap_refusal(info, settings, uuid):
    """Args:
        info: ``ldap_info`` of the sign-in.
        settings: the ``infinito_rbac`` site config.
        uuid: the ``entryUUID`` of the directory entry, None while
            ``directory_ids`` is off.

    Returns:
        Why the LDAP sign-in may not land on its account, or None when it may.
    """
    if uuid is None:
        return "the deploy no longer connects this site to the directory"
    email = info["email"]
    if not isinstance(email, str) or not email:
        return "the directory entry has no e-mail address"
    username = info[settings["username_claim"]]
    if not isinstance(username, str) or not username:
        return "the directory entry has no username"
    groups = info[settings["groups_claim"]]
    if not groups:
        return "the directory user holds no group that grants an ERPNext role"
    return account_refusal(email, username, groups, settings, uuid)


class DirectoryLDAPSettings(LDAPSettings):
    def create_or_update_user(self, user_data, groups=None):
        """Args:
            user_data: ``convert_ldap_entry_to_dict`` of the directory entry.
            groups: the ``cn`` of every directory group that holds the entry, or None.

        Returns:
            The account of the LDAP sign-in, guarded and converged.

        Raises:
            frappe.PermissionError: the sign-in may not land on its account.
        """
        settings = frappe.conf[SETTINGS_KEY]
        user_data = {**user_data, "username": first_value(user_data["username"])}
        info = ldap_info(user_data, groups, settings)
        uuid, shared = directory_entry(self, user_data["username"], info["email"])
        logger = frappe.logger(SETTINGS_KEY)
        reason = shared_refusal(
            shared, info["email"], user_data["username"], uuid, settings
        )
        if reason is None:
            reason = ldap_refusal(info, settings, uuid)
        if reason is not None:
            logger.warning(
                "REFUSED LDAP sign-in of %s as %s: %s",
                user_data["username"],
                info["email"],
                reason,
            )
            frappe.throw(f"LDAP sign-in refused: {reason}.", frappe.PermissionError)
        for line in converge(info, settings, uuid):
            logger.info(line)
        user = frappe.get_doc("User", info["email"])
        if not is_protected(info["email"], settings):
            self.update_user_fields(user=user, user_data=user_data)
        return user
