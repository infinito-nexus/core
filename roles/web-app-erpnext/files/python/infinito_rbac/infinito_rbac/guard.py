import frappe

from infinito_rbac.roles import (
    bound_accounts,
    identified_accounts,
    ids_claimed,
    linked_userids,
    owns_protected,
    protected_owners,
    recorded_ids,
)

PROVIDER = "keycloak"
SHARED_ADDRESS = "more than one directory entry holds this address"
PROTECTED_ACCOUNT = "the ERPNext account is protected and not this directory user's own"


def group_path(group):
    """Args:
        group: a group path, with or without its outer slashes.

    Returns:
        The path with one leading slash and no trailing one.
    """
    return "/" + group.strip("/")


def binding_providers(settings):
    """Args:
        settings: the ``infinito_rbac`` site config.

    Returns:
        The providers whose ``User Social Login`` rows bind an account to a
        directory user.
    """
    return {PROVIDER, settings["directory_provider"]}


def is_protected(name, settings):
    """Args:
        name: the account's name, in ``normal_address`` form.
        settings: the ``infinito_rbac`` site config.

    Returns:
        Whether the account is one of the protected users.
    """
    return name in {user.lower() for user in settings["protected_users"]}


def grants_of(mapping):
    """Args:
        mapping: ``{group path: [ERPNext role, ...]}``.

    Returns:
        ``{normalized group path: {ERPNext role, ...}}``, uniting the roles of one
        group's spellings.
    """
    grants = {}
    for group, roles in mapping.items():
        grants.setdefault(group_path(group), set()).update(roles)
    return grants


def shared_refusal(shared, name, userid, uuid, settings):
    """Args:
        shared: whether more than one directory entry holds the address.
        name: the account's name, in ``normal_address`` form.
        userid: the directory user's userid.
        uuid: ``directory_entry``'s id of the userid, "" unless exactly one entry
            holds it.
        settings: the ``infinito_rbac`` site config.

    Returns:
        ``SHARED_ADDRESS`` while more than one entry holds the address, None when
        none does or the account is a protected one whose row names the userid
        of the one entry that holds it.
    """
    if not shared:
        return None
    if uuid and is_protected(name, settings) and frappe.db.exists("User", name):
        user = frappe.get_doc("User", name)
        if userid.lower() in linked_userids(user, binding_providers(settings)):
            return None
    return SHARED_ADDRESS


def protected_refusal(name, userid, settings, uuid):
    """Args:
        name: the protected account's name, in ``normal_address`` form.
        userid: the directory user's userid.
        settings: the ``infinito_rbac`` site config.
        uuid: ``directory_entry``'s id of the userid, "" unless exactly one entry
            holds it, None while ``directory_ids`` is off.

    Returns:
        ``PROTECTED_ACCOUNT`` unless the account exists, ``owns_protected`` holds
        for the userid and, with ``directory_ids`` on, exactly one entry holds it;
        else None.
    """
    if uuid == "" or not frappe.db.exists("User", name):
        return PROTECTED_ACCOUNT
    if owns_protected(
        frappe.get_doc("User", name),
        userid,
        binding_providers(settings),
        protected_owners(settings["protected_owners"]),
    ):
        return None
    return PROTECTED_ACCOUNT


def account_refusal(name, userid, groups, settings, uuid):
    """Args:
        name: the account's name, in ``normal_address`` form.
        userid: the directory user's userid.
        groups: the group paths the sign-in carries, or None.
        settings: the ``infinito_rbac`` site config.
        uuid: the ``entryUUID`` of the directory user, "" when the directory holds
            no single entry for the userid, None while ``directory_ids`` is off;
            ignored for the protected users.

    Returns:
        Why the sign-in may not land on the account, or None when it may.
    """
    if is_protected(name, settings):
        return protected_refusal(name, userid, settings, uuid)
    if uuid == "":
        return "the directory holds no single entry for this username"
    providers = binding_providers(settings)
    if not frappe.db.exists("User", name):
        if bound_accounts(userid, providers) or (uuid and identified_accounts(uuid)):
            return (
                "the ERPNext account of this directory user still carries its "
                "former address until the directory sync renames it or creates "
                "a new one"
            )
        return None
    ids = recorded_ids(name)
    if uuid and ids == {uuid}:
        return None
    user = frappe.get_doc("User", name)
    linked = linked_userids(user, providers)
    if linked and userid.lower() not in linked:
        return "the ERPNext account belongs to another directory user"
    if uuid and ids:
        return (
            "the directory id recorded with the ERPNext account is not the one "
            "the directory holds for this username"
        )
    if uuid and not user.enabled:
        return (
            "the disabled ERPNext account carries no directory id, "
            "so only an administrator can reopen it"
        )
    if uuid and linked and ids_claimed():
        return (
            "the ERPNext account carries no directory id, "
            "so only an administrator can hand it to a directory user"
        )
    if linked:
        return None

    role_groups = set(grants_of(settings["role_grants"]))
    if isinstance(groups, list) and role_groups & {
        group_path(group) for group in groups
    }:
        return None
    return (
        "the ERPNext account is not linked to this directory user, "
        "and the directory user holds no ERPNext role group"
    )
