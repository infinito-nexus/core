# nocheck: mirrored-unit-test - imports pretix.base.models at module level and runs inside
# `pretix shell_scoped`; the models are not importable outside the Pretix image
"""Converge the native Pretix platform administrator and lock the upstream default account.

Environment:
    ADMIN_EMAIL:    login e-mail of the native administrator; empty while SSO
                    is on, where pretix-oidc creates the account and grants staff.
    ADMIN_PASSWORD: password the native administrator converges on.

Prints ``PRETIX_RESULT=CHANGED`` or ``PRETIX_RESULT=UNCHANGED``, suffixed with
``+FOREIGN`` when ADMIN_EMAIL belongs to an account of another authentication
backend, which stays untouched.
"""

import os

from pretix.base.models import User

PLACEHOLDER_EMAIL = "admin@localhost"
EMAIL = os.environ["ADMIN_EMAIL"]
PASSWORD = os.environ["ADMIN_PASSWORD"]


def lock_placeholder():
    user = User.objects.filter(
        email__iexact=PLACEHOLDER_EMAIL, auth_backend="native"
    ).first()
    if user is None or (not user.is_active and not user.has_usable_password()):
        return False
    user.set_unusable_password()
    user.is_active = False
    user.save()
    return True


def converge_admin():
    if not EMAIL:
        return False, False
    user = User.objects.filter(email__iexact=EMAIL).first()
    if user is None:
        User.objects.create_user(EMAIL, PASSWORD, is_staff=True)
        return True, False
    if user.auth_backend != "native":
        return False, True
    dirty = not user.check_password(PASSWORD) or not user.is_staff or not user.is_active
    if dirty:
        user.set_password(PASSWORD)
        user.is_staff = True
        user.is_active = True
        user.save()
    return dirty, False


locked = lock_placeholder()
changed, foreign = converge_admin()
result = "CHANGED" if locked or changed else "UNCHANGED"
print("PRETIX_RESULT=" + result + ("+FOREIGN" if foreign else ""))
