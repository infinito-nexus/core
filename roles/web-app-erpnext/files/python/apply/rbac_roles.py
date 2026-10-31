"""Converge the ERPNext roles and accounts the directory owns on its role groups.

Environment:
    SITE_NAME: the Frappe site.
    ROLE_GRANTS_JSON: JSON ``{role: [ERPNext role, ...]}`` of every declared role.
    ROLE_MEMBERS_JSON: JSON ``{role: [{username, email, name}]}`` of every declared role.
    PROTECTED_USERS_JSON: JSON list of user names the run never demotes or disables.
    SSO_PROVIDER_NAME: the Social Login Key whose ``User Social Login`` row a Keycloak
        sign-in writes; that row marks an account directory-owned.
    DIRECTORY_PROVIDER_NAME: provider of the ``User Social Login`` row the run writes on
        every member, because an LDAP sign-in leaves no mark on its account.

Output:
    One ``CHANGED <user> <change>`` line per change, else ``UNCHANGED``.
"""

import json
import os

import frappe

SITES_PATH = "/home/frappe/frappe-bench/sites"


def wanted_roles(grants, members):
    """Return ``{email: {"username", "roles"}}`` for every member with an e-mail.

    Args:
        grants: ``{role: [ERPNext role, ...]}``.
        members: ``{role: [members]}``.
    """
    wanted = {}
    for role, entries in members.items():
        for member in entries:
            email = member["email"].strip().lower()
            if email:
                wanted.setdefault(
                    email, {"username": member["username"], "roles": set()}
                )
                wanted[email]["roles"].update(grants[role])
    return wanted


def provision(email, username):
    """Create the enabled website account of a member and return it.

    Args:
        email: the member's e-mail, the account's name.
        username: the member's username.
    """
    user = frappe.new_doc("User")
    user.email = email
    user.username = username
    user.first_name = username
    user.enabled = 1
    user.send_welcome_email = 0
    user.user_type = "Website User"
    user.new_password = frappe.generate_hash()
    user.flags.ignore_permissions = True
    user.flags.no_welcome_mail = True
    user.insert()
    return user


def set_enabled(user, enabled):
    """Save the enabled state of an account.

    Args:
        user: the ``User`` document.
        enabled: 1 or 0.
    """
    user.enabled = enabled
    user.flags.ignore_permissions = True
    user.save()


def link(user, provider, username):
    """Save the ``User Social Login`` row that marks an account directory-owned.

    Args:
        user: the ``User`` document.
        provider: the row's provider.
        username: the member's username, the row's user ID.
    """
    user.append(
        "social_logins",
        {"provider": provider, "userid": username, "username": username},
    )
    user.flags.ignore_permissions = True
    user.save()


def reconcile(grants, members, protected, sso_provider, directory_provider):
    """Converge every directory-owned account and return one line per change.

    Args:
        grants: ``{role: [ERPNext role, ...]}``.
        members: ``{role: [members]}``.
        protected: lower-cased user names the run never demotes or disables.
        sso_provider: the provider of the row a Keycloak sign-in writes.
        directory_provider: the provider of the row this run writes.
    """
    lines = []
    managed = {erpnext_role for roles in grants.values() for erpnext_role in roles}
    providers = {sso_provider, directory_provider}
    wanted = wanted_roles(grants, members)

    for email, entry in sorted(wanted.items()):
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = provision(email, entry["username"])
            lines.append(f"CHANGED {email} created")
        if not user.enabled:
            set_enabled(user, 1)
            lines.append(f"CHANGED {email} enabled")
        linked = {row.provider for row in user.get("social_logins")} & providers
        if email not in protected and not linked:
            link(user, directory_provider, entry["username"])
            lines.append(f"CHANGED {email} linked {directory_provider}")
        current = {row.role for row in user.get("roles")}
        missing = entry["roles"] - current
        surplus = set() if email in protected else (current & managed) - entry["roles"]
        if missing:
            user.add_roles(*sorted(missing))
            lines.extend(f"CHANGED {email} granted {role}" for role in sorted(missing))
        if surplus:
            user.remove_roles(*sorted(surplus))
            lines.extend(f"CHANGED {email} revoked {role}" for role in sorted(surplus))

    owned = set(
        frappe.get_all(
            "User Social Login",
            filters={"provider": ["in", sorted(providers)], "parenttype": "User"},
            pluck="parent",
        )
    )
    for name in sorted(owned):
        lowered = name.lower()
        if lowered in protected or lowered in wanted:
            continue
        user = frappe.get_doc("User", name)
        current = {row.role for row in user.get("roles")}
        surplus = current & managed
        if surplus:
            user.remove_roles(*sorted(surplus))
            lines.extend(f"CHANGED {name} revoked {role}" for role in sorted(surplus))
        if user.enabled and not current - managed:
            set_enabled(user, 0)
            lines.append(f"CHANGED {name} disabled")
    return lines


def main(environ):
    """Converge the site and print the result.

    Args:
        environ: the process environment.
    """
    site = environ["SITE_NAME"]
    grants = json.loads(environ["ROLE_GRANTS_JSON"])
    members = json.loads(environ["ROLE_MEMBERS_JSON"])
    protected = {name.lower() for name in json.loads(environ["PROTECTED_USERS_JSON"])}
    sso_provider = environ["SSO_PROVIDER_NAME"]
    directory_provider = environ["DIRECTORY_PROVIDER_NAME"]

    frappe.init(site=site, sites_path=SITES_PATH)
    frappe.connect()
    try:
        lines = reconcile(grants, members, protected, sso_provider, directory_provider)
        frappe.db.commit()
    finally:
        frappe.destroy()
    print("\n".join(lines) if lines else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
