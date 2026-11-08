# nocheck: mirrored-unit-test - imports weblate.auth.models at module level and runs
# inside `weblate shell`; the models are not importable outside the Weblate image
"""Give the superuser Weblate bootstrapped the platform administrator's name.

Upstream's entrypoint calls ``createadmin`` without ``--username``, so the
superuser is always named ``admin`` while carrying the platform
administrator's e-mail. That is one human with two accounts, and it breaks
the OIDC login: ``associate_by_email`` matches the local account, then
``reauthenticate`` sees a usable password and parks an ``@partial`` on
``/accounts/confirm/`` asking for it. The partial is sticky, so every retry
returns to the same page.

Renaming keeps the account, and with it the API token the deploy reads back;
creating a second superuser would leave that token behind.

The password is only dropped while SSO is on. Without SSO it is the only way
in, and ``playwright.env.j2`` hands it to the native-login round.

Fed to ``weblate shell`` on stdin. Every value arrives in the environment and
none has a default: a missing one is a deploy bug and must stop the run.
"""

import os

from weblate.auth.models import User

bootstrap = os.environ["WEBLATE_ADMIN_BOOTSTRAP_USERNAME"]
target = os.environ["WEBLATE_ADMIN_USERNAME"]
sso_enabled = os.environ["WEBLATE_OIDC_ENABLED"] == "true"

changed = False

if bootstrap != target:
    stale = User.objects.filter(username=bootstrap).first()
    if stale is not None:
        stale.username = target
        stale.save(update_fields=["username"])
        changed = True

admin = User.objects.get(username=target)

if sso_enabled and admin.has_usable_password():
    admin.set_unusable_password()
    admin.save(update_fields=["password"])
    changed = True

print("ADOPTED=1" if changed else "ADOPTED=0")
