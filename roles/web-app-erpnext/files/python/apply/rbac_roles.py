"""Environment:
    SITE_NAME: the Frappe site.
    ROLE_GRANTS_JSON: JSON ``{group path: [ERPNext role, ...]}`` of the role groups of
        this role.
    GROUP_ROLES_JSON: JSON ``{group path: [ERPNext role, ...]}`` of
        ``services.erpnext.group_roles``.
    ROLE_MEMBERS_JSON: JSON ``{group path: [{username, email, name, uuid}]}`` of the
        groups of both mappings; ``uuid`` is the ``entryUUID`` of the member's
        directory entry, absent where the members come from the inventory.
    PROTECTED_USERS_JSON: JSON list of user names the run never demotes or disables.
    PROTECTED_OWNERS_JSON: JSON ``ERPNEXT_RBAC_PROTECTED_OWNERS``, ``{protected
        user name: username}`` of the protected accounts the run creates for, and
        without a ``User Social Login`` row grants to, the member of that username.
    SSO_PROVIDER_NAME: the Social Login Key whose ``User Social Login`` row a Keycloak
        sign-in writes.
    DIRECTORY_PROVIDER_NAME: provider of the ``User Social Login`` row the run writes on
        every member.
    DIRECTORY_IDS_JSON: JSON ``true`` when accounts are bound to the ``entryUUID`` of
        their directory entries; with ``false`` the run ignores every ``uuid`` and
        record.
    DIRECTORY_UUID_ATTRIBUTE: the directory attribute that holds an entry's
        immutable id.

Output:
    One ``CHANGED <user> <change>`` line per change and one ``REFUSED <user>
    <reason>`` line per member's account or address the run leaves alone, else
    ``UNCHANGED``.
"""

import json
import os

import frappe
from infinito_rbac.reclaim import reclaim, unsettled_reclaims
from infinito_rbac.roles import (
    ambiguous_holders,
    bound_accounts,
    converge_mapped,
    ensure_roles,
    identified_accounts,
    ids_claimed,
    linked_userids,
    mapped_grants,
    mark_ids_claimed,
    move_records,
    normal_address,
    owns_protected,
    protected_owners,
    provision,
    rebind,
    record_id,
    recorded_ids,
)

SITES_PATH = "/home/frappe/frappe-bench/sites"
PROTECTED_REASON = "the account is protected and not the member's own"


def wanted_roles(grants, members, directory_ids, protected):
    """Args:
        grants: ``{group: [ERPNext role, ...]}``.
        members: ``{group: [members]}``, holding every group of ``grants``.
        directory_ids: whether the members' ``uuid`` binds accounts; ``uuid`` is
            None without.
        protected: lower-cased user names that never carry a directory id; their
            ``uuid`` is None.

    Returns:
        ``{email: {"username", "uuid", "roles"}}`` for every member with an e-mail,
        the e-mail in ``normal_address`` form.
    """
    wanted = {}
    for role in grants:
        for member in members[role]:
            email = normal_address(member["email"])
            if email:
                bound = directory_ids and email not in protected
                wanted.setdefault(
                    email,
                    {
                        "username": member["username"],
                        "uuid": member.get("uuid", "") if bound else None,
                        "roles": set(),
                    },
                )
                wanted[email]["roles"].update(grants[role])
    return wanted


def ambiguous_addresses(groups, members):
    """Args:
        groups: the groups of both mappings.
        members: ``{group: [members]}``, holding every one of the groups.

    Returns:
        The addresses, in ``normal_address`` form, more than one directory entry
        among the members holds.
    """
    holders = {}
    for group in groups:
        for member in members[group]:
            email = normal_address(member["email"])
            if email:
                holders.setdefault(email, []).append(
                    ([member["username"]], member.get("uuid", ""))
                )
    return {email for email, entries in holders.items() if ambiguous_holders(entries)}


def identified(user, entry):
    """Args:
        user: the ``User`` document.
        entry: the member's ``wanted_roles`` entry.

    Returns:
        Whether the account's recorded directory id is the member's.
    """
    return bool(entry["uuid"]) and recorded_ids(user.name) == {entry["uuid"]}


def refusal(user, entry, providers, claiming):
    """Args:
        user: the ``User`` document at the member's address.
        entry: the member's ``wanted_roles`` entry.
        providers: the providers whose rows bind an account to a member.
        claiming: whether this is the first run with directory ids.

    Returns:
        Why the account at the member's address may not be the member's, or None
        when it may.
    """
    if identified(user, entry):
        return None
    linked = linked_userids(user, providers)
    if linked and entry["username"].lower() not in linked:
        return "a row binds it to another directory user"
    if entry["uuid"] is None:
        return None
    if recorded_ids(user.name):
        return "its recorded directory id is not the member's"
    if not user.enabled:
        return "it is disabled and carries no directory id"
    if linked and not claiming:
        return "it carries no directory id"
    return None


def claim(user, entry):
    """Args:
        user: the account, bound to the member.
        entry: the member's ``wanted_roles`` entry.

    Returns:
        One line per directory id recorded with an account that carried none.
    """
    if not entry["uuid"] or recorded_ids(user.name):
        return []
    record_id(user.name, entry["uuid"])
    return [f"CHANGED {user.name} recorded its directory id"]


def mapped_roles(mapped, email, user, providers, claiming):
    """Args:
        mapped: ``wanted_roles`` of the mapped groups' members.
        email: the address of a directory-owned account, in ``normal_address`` form.
        user: that account.
        providers: the providers whose rows bind an account to a member.
        claiming: whether this is the first run with directory ids.

    Returns:
        The roles of ``services.erpnext.group_roles`` the member of the address
        holds, if the account is bound to that member.
    """
    entry = mapped.get(email)
    if entry is None or refusal(user, entry, providers, claiming) is not None:
        return set()
    if identified(user, entry) or entry["username"].lower() in linked_userids(
        user, providers
    ):
        return entry["roles"]
    return set()


def set_enabled(user, enabled):
    """Args:
    user: the ``User`` document.
    enabled: 1 or 0.
    """
    user.enabled = enabled
    user.flags.ignore_permissions = True
    user.save()


def link(user, provider, username):
    """Args:
    user: the ``User`` document.
    provider: the provider of the ``User Social Login`` row the account gets.
    username: the member's username, the row's user ID.
    """
    user.append(
        "social_logins",
        {"provider": provider, "userid": username, "username": username},
    )
    user.flags.ignore_permissions = True
    user.save()


def former_account(kept, uuid):
    """Args:
        kept: lower-cased names of the accounts that stay where they are: every
            member's address and the protected users.
        uuid: the member's ``entryUUID``, empty or None without one.

    Returns:
        The one account outside ``kept`` whose only recorded directory id is the
        member's, or None.
    """
    if not uuid:
        return None
    adoptable = {
        name
        for name in identified_accounts(uuid)
        if name.lower() not in kept and recorded_ids(name) == {uuid}
    }
    return adoptable.pop() if len(adoptable) == 1 else None


def settle(email, entry, kept, providers, provider, create):
    """Args:
        email: the member's address, the account's name.
        entry: the member's ``wanted_roles`` entry.
        kept: lower-cased names of the accounts that stay where they are.
        providers: the providers whose rows bind an account to a member.
        provider: the provider of the row that links a new account.
        create: whether a member bound to no account gets a new one.

    Returns:
        One line per change that gives the member without an account at its
        address its former account or a new one.
    """
    former = former_account(kept, entry["uuid"])
    if former is not None:
        frappe.rename_doc("User", former, email, show_alert=False)
        move_records(former, email)
        return [f"CHANGED {former} renamed to {email}"]
    if not create and not bound_accounts(entry["username"], providers):
        return []
    provision(email, entry["username"], provider)
    lines = [f"CHANGED {email} created"]
    if entry["uuid"]:
        record_id(email, entry["uuid"])
        lines.append(f"CHANGED {email} recorded its directory id")
    return lines


def protected_refusal(email, entry, providers, owners):
    """Args:
        email: a protected user name a member's address names.
        entry: the member's ``wanted_roles`` entry.
        providers: the providers whose rows bind an account to a member.
        owners: ``protected_owners`` of ``ERPNEXT_RBAC_PROTECTED_OWNERS``.

    Returns:
        ``PROTECTED_REASON`` unless ``owns_protected`` holds for the member on
        the existing account, or ``owners`` names the member for a missing one;
        else None.
    """
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        owned = owns_protected(user, entry["username"], providers, owners)
    else:
        owned = owners.get(email) == entry["username"].lower()
    return None if owned else PROTECTED_REASON


def reconcile(
    grants,
    group_roles,
    members,
    protected,
    owners,
    providers,
    directory,
):
    """Args:
        grants: ``{group: [ERPNext role, ...]}`` of the role groups of this role.
        group_roles: ``{group: [ERPNext role, ...]}`` of
            ``services.erpnext.group_roles``.
        members: ``{group: [members]}`` of every group of both mappings.
        protected: lower-cased user names the run never demotes, disables or renames.
        owners: ``protected_owners`` of ``ERPNEXT_RBAC_PROTECTED_OWNERS``.
        providers: ``(sso_provider, directory_provider)``, the providers of the row
            a Keycloak sign-in writes and of the row this run writes.
        directory: the directory attribute that holds an entry's immutable id
            while the members' ``entryUUID`` binds accounts, else None.

    Returns:
        One line per change to the directory-owned accounts and per refusal.
    """
    managed = {erpnext_role for roles in grants.values() for erpnext_role in roles}
    directory_provider = providers[1]
    providers = set(providers)
    directory_ids = directory is not None
    ambiguous = ambiguous_addresses([*grants, *group_roles], members)
    lines = [
        f"REFUSED {email} more than one directory entry holds its address"
        for email in sorted(ambiguous)
    ]
    wanted = {
        email: entry
        for email, entry in wanted_roles(
            grants, members, directory_ids, protected
        ).items()
        if email not in ambiguous
    }
    mapped = {
        email: entry
        for email, entry in wanted_roles(
            group_roles, members, directory_ids, protected
        ).items()
        if email not in ambiguous
    }
    kept = set(wanted) | set(mapped) | protected | ambiguous
    claiming = directory_ids and not ids_claimed()
    handled = set()

    for email, entry in sorted(wanted.items()):
        reason = (
            protected_refusal(email, entry, providers, owners)
            if email in protected
            else None
        )
        if reason is not None:
            lines.append(f"REFUSED {email} {reason}")
            continue
        if not frappe.db.exists("User", email):
            lines.extend(
                settle(email, entry, kept, providers, directory_provider, True)
            )
        user = frappe.get_doc("User", email)
        if email not in protected:
            lines.extend(reclaim(user, entry, providers, directory))
        reason = (
            None if email in protected else refusal(user, entry, providers, claiming)
        )
        if reason is not None:
            lines.append(f"REFUSED {email} {reason}")
            continue
        handled.add(email)
        if not user.enabled:
            set_enabled(user, 1)
            lines.append(f"CHANGED {email} enabled")
        linked = {row.provider for row in user.get("social_logins")} & providers
        if email not in protected and not linked:
            link(user, directory_provider, entry["username"])
            lines.append(f"CHANGED {email} linked {directory_provider}")
        if email not in protected:
            lines.extend(claim(user, entry))
        if email not in protected and identified(user, entry):
            lines.extend(rebind(user, entry["username"], providers))
        current = {row.role for row in user.get("roles")}
        missing = entry["roles"] - current
        surplus = set() if email in protected else (current & managed) - entry["roles"]
        if missing:
            lines.extend(ensure_roles(missing))
            user.add_roles(*sorted(missing))
            lines.extend(f"CHANGED {email} granted {role}" for role in sorted(missing))
        if surplus:
            user.remove_roles(*sorted(surplus))
            lines.extend(f"CHANGED {email} revoked {role}" for role in sorted(surplus))
        if email not in protected:
            lines.extend(
                converge_mapped(
                    user, mapped_roles(mapped, email, user, providers, claiming)
                )
            )

    for email, entry in sorted(mapped.items()):
        if email in wanted or frappe.db.exists("User", email):
            continue
        reason = (
            protected_refusal(email, entry, providers, owners)
            if email in protected
            else None
        )
        if reason is not None:
            lines.append(f"REFUSED {email} {reason}")
            continue
        lines.extend(settle(email, entry, kept, providers, directory_provider, False))

    owned = set(
        frappe.get_all(
            "User Social Login",
            filters={"provider": ["in", sorted(providers)], "parenttype": "User"},
            pluck="parent",
        )
    )
    for name in sorted(owned):
        lowered = name.lower()
        if lowered in protected or lowered in handled:
            continue
        user = frappe.get_doc("User", name)
        current = {row.role for row in user.get("roles")}
        recorded = mapped_grants(name)
        if lowered in mapped:
            lines.extend(reclaim(user, mapped[lowered], providers, directory))
            reason = refusal(user, mapped[lowered], providers, claiming)
            if reason is not None:
                lines.append(f"REFUSED {name} {reason}")
        member_roles = mapped_roles(mapped, lowered, user, providers, claiming)
        surplus = current & managed
        if surplus:
            user.remove_roles(*sorted(surplus))
            lines.extend(f"CHANGED {name} revoked {role}" for role in sorted(surplus))
        if member_roles:
            lines.extend(claim(user, mapped[lowered]))
        if member_roles and identified(user, mapped[lowered]):
            lines.extend(rebind(user, mapped[lowered]["username"], providers))
        if member_roles and not user.enabled:
            set_enabled(user, 1)
            lines.append(f"CHANGED {name} enabled")
        lines.extend(converge_mapped(user, member_roles))
        if not member_roles and user.enabled and not current - managed - recorded:
            set_enabled(user, 0)
            lines.append(f"CHANGED {name} disabled")

    lines.extend(unsettled_reclaims(protected))

    if claiming and any(
        entry["uuid"] for entry in (*wanted.values(), *mapped.values())
    ):
        mark_ids_claimed()
        lines.append("CHANGED directory ids claimed")
    return lines


def main(environ):
    """Args:
    environ: the process environment.
    """
    site = environ["SITE_NAME"]
    grants = json.loads(environ["ROLE_GRANTS_JSON"])
    group_roles = json.loads(environ["GROUP_ROLES_JSON"])
    members = json.loads(environ["ROLE_MEMBERS_JSON"])
    protected = {name.lower() for name in json.loads(environ["PROTECTED_USERS_JSON"])}
    owners = protected_owners(json.loads(environ["PROTECTED_OWNERS_JSON"]))
    providers = (environ["SSO_PROVIDER_NAME"], environ["DIRECTORY_PROVIDER_NAME"])
    directory = (
        environ["DIRECTORY_UUID_ATTRIBUTE"]
        if json.loads(environ["DIRECTORY_IDS_JSON"]) is True
        else None
    )

    frappe.init(site=site, sites_path=SITES_PATH)
    frappe.connect()
    try:
        lines = reconcile(
            grants, group_roles, members, protected, owners, providers, directory
        )
        frappe.db.commit()
    finally:
        frappe.destroy()
    print("\n".join(lines) if lines else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
