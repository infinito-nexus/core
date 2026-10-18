import os

from baserow.core.handler import CoreHandler
from baserow.core.models import UserProfile
from baserow.core.user.utils import normalize_email_address
from django.contrib.auth import get_user_model

username = os.environ["BOOTSTRAP_ADMIN_USERNAME"]
email = normalize_email_address(os.environ["BOOTSTRAP_ADMIN_EMAIL"])
password = os.environ["BOOTSTRAP_ADMIN_PASSWORD"]

User = get_user_model()

u = (
    User.objects.filter(username=email).first()
    or User.objects.filter(username=username).first()
    or User.objects.filter(first_name=username, is_superuser=True)
    .order_by("id")
    .first()
)
created = u is None
changed = False

if created:
    u = User.objects.create(
        username=email,
        email=email,
        first_name=username,
        is_staff=True,
        is_superuser=True,
    )
    u.set_password(password)
    u.save()
else:
    user_updates = []
    for field in ("username", "email"):
        if getattr(u, field) != email:
            setattr(u, field, email)
            user_updates.append(field)
    if not u.first_name:
        u.first_name = username
        user_updates.append("first_name")
    for flag in ("is_staff", "is_superuser"):
        if not getattr(u, flag):
            setattr(u, flag, True)
            user_updates.append(flag)
    if not u.check_password(password):
        u.set_password(password)
        user_updates.append("password")
    if user_updates:
        u.save(update_fields=user_updates)
        changed = True

profile, profile_created = UserProfile.objects.get_or_create(user=u)
profile_updates = []
if profile.email_verified is not True:
    profile.email_verified = True
    profile_updates.append("email_verified")
if profile.completed_onboarding is not True:
    profile.completed_onboarding = True
    profile_updates.append("completed_onboarding")
if profile_updates:
    profile.save(update_fields=profile_updates)

settings = CoreHandler().get_settings()
if settings.show_admin_signup_page:
    settings.show_admin_signup_page = False
    settings.save(update_fields=["show_admin_signup_page"])
    changed = True

print(
    "BOOTSTRAP_STATE="
    + (
        "changed"
        if created or changed or profile_created or profile_updates
        else "unchanged"
    )
)
