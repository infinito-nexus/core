"""Give the superuser Weblate bootstrapped the platform administrator's name and SSO identity.

Upstream's entrypoint calls ``createadmin`` without ``--username``, so the
superuser is always named ``admin`` while carrying the platform
administrator's e-mail. Renaming keeps the account, and with it the API
token the deploy reads back; creating a second superuser would leave that
token behind.

Since Weblate 2026.11 ``weblate.accounts.pipeline.associate_by_email``
refuses a signed-out OIDC sign-in whose e-mail already belongs to a local
account (``email_in_use``) unless ``REGISTRATION_REBIND`` is on, and that
setting would let every Keycloak user take over any account by e-mail. So
the administrator is bound to exactly its own Keycloak user instead: a
``social_django`` association for the ``WEBLATE_OIDC_BACKEND`` provider
whose ``uid`` is the Keycloak user id, which Keycloak sends as the ``sub``
claim.
``social_user`` then finds the administrator before any e-mail check runs.
An association with that id held by another account is moved to the
administrator. An administrator already bound to another subject stops the
run, so a foreign identity is never overwritten silently.

The password is only dropped while SSO is on. Without SSO it is the only way
in, and ``playwright.env.j2`` hands it to the native-login round. With SSO it
also keeps ``reauthenticate`` from parking a sticky ``@partial`` on
``/accounts/confirm/`` should the association ever be missing.

Fed to ``weblate shell`` on stdin. Every value arrives in the environment and
none has a default: a missing one is a deploy bug and must stop the run.
``WEBLATE_ADMIN_OIDC_UID`` is empty while SSO is off.
"""

import os

from social_django.models import UserSocialAuth
from weblate.auth.models import User

OIDC_ID_KEY = "sub"

bootstrap = os.environ["WEBLATE_ADMIN_BOOTSTRAP_USERNAME"]
target = os.environ["WEBLATE_ADMIN_USERNAME"]
sso_enabled = os.environ["WEBLATE_OIDC_ENABLED"] == "true"
backend = os.environ["WEBLATE_OIDC_BACKEND"]
subject = os.environ["WEBLATE_ADMIN_OIDC_UID"]

changed = False

if bootstrap != target:
    stale = User.objects.filter(username=bootstrap).first()
    if stale is not None:
        stale.username = target
        stale.save(update_fields=["username"])
        changed = True

admin = User.objects.get(username=target)

if sso_enabled:
    if not subject:
        raise SystemExit(
            f"ADOPT_REFUSED: SSO is on but no Keycloak subject arrived for '{target}'"
        )
    foreign = UserSocialAuth.objects.filter(user=admin, provider=backend).exclude(
        uid=subject
    )
    if foreign.exists():
        raise SystemExit(
            f"ADOPT_REFUSED: '{target}' is already bound to another OIDC subject; check "
            "which Keycloak user it belongs to and delete that row from "
            "social_auth_usersocialauth before deploying again"
        )
    binding = UserSocialAuth.objects.filter(provider=backend, uid=subject).first()
    if binding is None:
        UserSocialAuth.objects.create(
            user=admin, provider=backend, uid=subject, id_key=OIDC_ID_KEY
        )
        changed = True
    elif binding.user_id != admin.pk or binding.id_key != OIDC_ID_KEY:
        binding.user = admin
        binding.id_key = OIDC_ID_KEY
        binding.save(update_fields=["user", "id_key"])
        changed = True

if sso_enabled and admin.has_usable_password():
    admin.set_unusable_password()
    admin.save(update_fields=["password"])
    changed = True

print("ADOPTED=1" if changed else "ADOPTED=0")
