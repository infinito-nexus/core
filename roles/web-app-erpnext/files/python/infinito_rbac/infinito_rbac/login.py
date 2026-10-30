"""Converge one account on its role groups when it signs in through Keycloak.

``hooks.py`` routes Frappe's Keycloak callback here. The account gets what the
RBAC hook of ``sys-ctl-mtn-rbac-sync`` gives it on its timer, before Frappe
decides whether it may sign in.

Site config ``infinito_rbac`` (written by ``files/python/apply/login/rbac.py``):
    groups_claim: userinfo claim with the full paths of the user's groups.
    username_claim: userinfo claim with the username of a new account.
    given_name_claim: userinfo claim with the first name.
    family_name_claim: userinfo claim with the last name.
    role_grants: ``{group path: [ERPNext role, ...]}`` of every role group.
    protected_users: user names a sign-in never changes.
"""

import frappe
from frappe.integrations.oauth2_logins import decoder_compat
from frappe.utils.oauth import get_email, get_info_via_oauth, login_oauth_user

PROVIDER = "keycloak"
SETTINGS_KEY = "infinito_rbac"


def _path(group):
    return "/" + group.strip("/")


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
    user.save()


def refresh_profile(user, info, settings):
    """Copy first and last name from the sign-in and return one line per change.

    Args:
        user: the ``User`` document.
        info: the userinfo of the sign-in.
        settings: the ``infinito_rbac`` site config.
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


def converge(info, settings):
    """Apply the role groups of one sign-in to its account and return one line per change.

    Args:
        info: the userinfo of the sign-in.
        settings: the ``infinito_rbac`` site config.
    """
    email = get_email(info)
    if not email:
        return []
    email = email.strip().lower()
    if email in {name.lower() for name in settings["protected_users"]}:
        return []
    claim = settings["groups_claim"]
    if claim not in info:
        frappe.throw(f"The Keycloak sign-in of {email} carries no {claim} claim")

    groups = {_path(group) for group in info[claim]}
    grants = {
        _path(group): set(roles) for group, roles in settings["role_grants"].items()
    }
    managed = set().union(*grants.values())
    held = [group for group in grants if group in groups]
    wanted = set().union(*(grants[group] for group in held))

    lines = []
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
    elif held:
        user = provision(email, info[settings["username_claim"]])
        lines.append(f"CHANGED {email} created")
    else:
        return lines
    user.flags.ignore_permissions = True

    if held and not user.enabled:
        set_enabled(user, 1)
        lines.append(f"CHANGED {email} enabled")
    if held:
        lines.extend(refresh_profile(user, info, settings))

    current = {row.role for row in user.get("roles")}
    missing = wanted - current
    surplus = (current & managed) - wanted
    if missing:
        user.add_roles(*sorted(missing))
        lines.extend(f"CHANGED {email} granted {role}" for role in sorted(missing))
    if surplus:
        user.remove_roles(*sorted(surplus))
        lines.extend(f"CHANGED {email} revoked {role}" for role in sorted(surplus))

    if not held and user.enabled:
        set_enabled(user, 0)
        lines.append(f"CHANGED {email} disabled")
    return lines


@frappe.whitelist(allow_guest=True)
def login_via_keycloak(code: str, state: str):
    """Replace ``frappe.integrations.oauth2_logins.login_via_keycloak``.

    Args:
        code: the authorization code Keycloak returned.
        state: the login attempt Frappe issued.
    """
    settings = frappe.conf[SETTINGS_KEY]
    info = get_info_via_oauth(PROVIDER, code, decoder=decoder_compat)
    for line in converge(info, settings):
        frappe.logger(SETTINGS_KEY).info(line)
    frappe.db.commit()
    login_oauth_user(info, provider=PROVIDER, state=state)
