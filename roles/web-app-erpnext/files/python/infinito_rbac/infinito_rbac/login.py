"""Guard a Keycloak sign-in, then converge its account on its role groups.

Frappe takes the account named after the sign-in's e-mail address and links it to
whoever signs in, so ``hooks.py`` routes both whitelisted callbacks that complete a
Keycloak sign-in here. ``refusal`` runs before any account changes; only a sign-in
it lets through has its account converged on what the RBAC hook of
``sys-ctl-mtn-rbac-sync`` gives it on its timer, before Frappe decides whether it
may sign in.

Site config ``infinito_rbac`` (written by ``files/python/apply/login/rbac.py``):
    groups_claim: userinfo claim with the full paths of the user's groups.
    username_claim: userinfo claim with the username of a new account.
    given_name_claim: userinfo claim with the first name.
    family_name_claim: userinfo claim with the last name.
    role_grants: ``{group path: [ERPNext role, ...]}`` of every role group.
    protected_users: user names a sign-in never changes.
    directory_provider: provider of the ``User Social Login`` row the RBAC hook
        writes on every member it provisions or adopts.
"""

import frappe
from frappe.integrations.oauth2_logins import custom as upstream_custom
from frappe.integrations.oauth2_logins import decoder_compat
from frappe.utils.oauth import get_email, get_info_via_oauth, login_oauth_user

PROVIDER = "keycloak"
SETTINGS_KEY = "infinito_rbac"


def _path(group):
    return "/" + group.strip("/")


def _providers(settings):
    return {PROVIDER, settings["directory_provider"]}


def owners(name, providers):
    """Return the lower-cased userids the account's ``User Social Login`` rows of the providers name.

    Args:
        name: the account's name.
        providers: the providers whose rows bind an account to a directory user.
    """
    return {
        row.userid.lower()
        for row in frappe.get_doc("User", name).get("social_logins")
        if row.provider in providers and row.userid
    }


def bound_accounts(userid, providers):
    """Return the names of the accounts a ``User Social Login`` row of the providers binds to the userid.

    Args:
        userid: the directory user's userid.
        providers: the providers whose rows bind an account to a directory user.
    """
    return set(
        frappe.get_all(
            "User Social Login",
            filters={
                "provider": ["in", sorted(providers)],
                "parenttype": "User",
                "userid": userid,
            },
            pluck="parent",
        )
    )


def refusal(info, userid_claim, settings):
    """Return why a Keycloak sign-in may not land on its account, or None when it may.

    Args:
        info: the userinfo of the sign-in.
        userid_claim: the claim Frappe stores as the userid of an account's ``keycloak`` row.
        settings: the ``infinito_rbac`` site config.
    """
    if info.get("email_verified") is not True:
        return "the e-mail address of the Keycloak account is not verified"
    email = get_email(info)
    if not isinstance(email, str) or not email.strip():
        return "the Keycloak account has no e-mail address"
    userid = info.get(userid_claim)
    if not isinstance(userid, str) or not userid:
        return f"the sign-in carries no {userid_claim} claim"

    providers = _providers(settings)
    name = email.strip().lower()
    if not frappe.db.exists("User", name):
        if bound_accounts(userid, providers):
            return (
                "the ERPNext account of this Keycloak account still carries its "
                "former address until the directory sync renames it"
            )
        return None
    linked = owners(name, providers)
    if linked:
        if userid.lower() in linked:
            return None
        return "the ERPNext account belongs to another Keycloak account"

    groups = info.get(settings["groups_claim"])
    role_groups = {_path(group) for group in settings["role_grants"]}
    if isinstance(groups, list) and role_groups & {_path(group) for group in groups}:
        return None
    return (
        "the ERPNext account is not linked to this Keycloak account, "
        "and the Keycloak account holds no ERPNext role group"
    )


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

    if not held and user.enabled and not current - managed:
        set_enabled(user, 0)
        lines.append(f"CHANGED {email} disabled")
    return lines


def guarded_login(code, state):
    """Converge and hand a Keycloak sign-in to Frappe once ``refusal`` finds nothing against it.

    Args:
        code: the authorization code Keycloak returned.
        state: the login attempt Frappe issued.
    """
    settings = frappe.conf[SETTINGS_KEY]
    userid_claim = frappe.db.get_value("Social Login Key", PROVIDER, "user_id_property")
    if not userid_claim:
        frappe.throw(
            f"Keycloak sign-in refused: the Social Login Key {PROVIDER} names no user_id_property.",
            frappe.PermissionError,
        )
    info = get_info_via_oauth(PROVIDER, code, decoder=decoder_compat)
    reason = refusal(info, userid_claim, settings)
    logger = frappe.logger(SETTINGS_KEY)
    if reason is not None:
        logger.warning(
            "REFUSED Keycloak sign-in of %s as %s: %s",
            info.get(userid_claim),
            get_email(info),
            reason,
        )
        frappe.throw(f"Keycloak sign-in refused: {reason}.", frappe.PermissionError)
    for line in converge(info, settings):
        logger.info(line)
    frappe.db.commit()
    login_oauth_user(info, provider=PROVIDER, state=state)


@frappe.whitelist(allow_guest=True)
def login_via_keycloak(code: str, state: str):
    """Replace ``frappe.integrations.oauth2_logins.login_via_keycloak``.

    Args:
        code: the authorization code Keycloak returned.
        state: the login attempt Frappe issued.
    """
    guarded_login(code, state)


@frappe.whitelist(allow_guest=True)
def custom(code: str, state: str):
    """Replace ``frappe.integrations.oauth2_logins.custom``, which completes the sign-in
    of whichever Social Login Key its path names, ``keycloak`` included.

    Args:
        code: the authorization code the provider returned.
        state: the login attempt Frappe issued.
    """
    path = frappe.request.path[1:].split("/")
    if len(path) == 4 and path[3].strip().lower() == PROVIDER:
        guarded_login(code, state)
        return
    upstream_custom(code, state)
