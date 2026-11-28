import frappe

from infinito_rbac.roles import (
    directory_holders,
    drop_reclaim,
    linked_userids,
    normal_address,
    reclaim_id,
    reclaim_requested,
    reclaim_requests,
)


def reclaim_refusal(user, entry, providers, attribute):
    """Args:
        user: the ``User`` document at the member's address.
        entry: the member's ``wanted_roles`` entry.
        providers: the providers whose rows bind an account to a member.
        attribute: the directory attribute that holds an entry's immutable id.

    Returns:
        Why a reclaim request may not hand the account to the member, or None when
        it may.
    """
    if not entry["uuid"]:
        return "the member carries no directory id"
    linked = linked_userids(user, providers)
    if linked and entry["username"].lower() not in linked:
        return "a row binds it to another directory user"
    try:
        found = directory_holders(
            frappe.get_single("LDAP Settings"),
            entry["username"],
            normal_address(user.name),
            attribute,
        )
    except Exception as error:
        return f"the directory could not be searched: {type(error).__name__}"
    if [uuid for _, uuid, _ in found] != [entry["uuid"]]:
        return "the directory entries with its username or address are not the member's alone"
    return None


def reclaim(user, entry, providers, attribute):
    """Args:
        user: the ``User`` document at the member's address.
        entry: the member's ``wanted_roles`` entry.
        providers: the providers whose rows bind an account to a member.
        attribute: the directory attribute that holds an entry's immutable id.

    Returns:
        One line per pending reclaim request of the account, settled or dropped.
    """
    if not reclaim_requested(user.name):
        return []
    reason = reclaim_refusal(user, entry, providers, attribute)
    if reason is not None:
        drop_reclaim(user.name)
        return [f"REFUSED {user.name} its reclaim request is dropped: {reason}"]
    reclaim_id(user.name, entry["uuid"])
    return [f"CHANGED {user.name} reclaimed its directory id"]


def unsettled_reclaims(protected):
    """Args:
        protected: lower-cased user names the run never changes.

    Returns:
        One line per reclaim request the run left pending, each dropped.
    """
    lines = []
    for name in sorted(reclaim_requests()):
        drop_reclaim(name)
        reason = (
            "the account is protected"
            if name.lower() in protected
            else "no member's account the run converged is at its address"
        )
        lines.append(f"REFUSED {name} its reclaim request is dropped: {reason}")
    return lines
