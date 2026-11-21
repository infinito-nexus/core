"""Move website self-signups without an identity provider link to the portal, once.

Selects the internal users whose ``create_uid`` is the public user and that
carry no ``oauth_uid``, except the login ``infinito.rbac`` protects, and sets
the system parameter ``infinito.rbac.signup_portal_reconciled`` afterwards;
a later run with the parameter set changes nothing.

Prints ``portal=<login>`` per moved user, then ``SIGNUP_PORTAL_CHANGED`` or
``SIGNUP_PORTAL_UNCHANGED``.
"""

env = globals()["env"]
MARKER = "infinito.rbac.signup_portal_reconciled"

parameters = env["ir.config_parameter"].sudo()
moved = env["res.users"]
if not parameters.get_param(MARKER):
    portal = env.ref("base.group_portal")
    internal = env.ref("base.group_user")
    rbac = env["infinito.rbac"]
    signups = (
        env["res.users"]
        .sudo()
        .with_context(active_test=False)
        .search(
            [
                ("create_uid", "=", env.ref("base.public_user").id),
                ("share", "=", False),
                ("oauth_uid", "=", False),
            ]
        )
    )
    for user in signups.filtered(lambda user: not rbac._is_protected(user.login)):
        rbac._apply(user, portal | internal, portal)
        print(f"portal={user.login}")
        moved |= user
    parameters.set_param(MARKER, "1")
    env.cr.commit()

print("SIGNUP_PORTAL_CHANGED" if moved else "SIGNUP_PORTAL_UNCHANGED")
