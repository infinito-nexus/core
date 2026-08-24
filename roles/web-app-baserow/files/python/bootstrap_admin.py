import os

from baserow.core.models import UserProfile
from django.contrib.auth import get_user_model

username = os.environ["BOOTSTRAP_ADMIN_USERNAME"]
email = os.environ["BOOTSTRAP_ADMIN_EMAIL"]
password = os.environ["BOOTSTRAP_ADMIN_PASSWORD"]

User = get_user_model()

u, created = User.objects.get_or_create(
    username=username,
    defaults={"email": email, "is_staff": True, "is_superuser": True},
)

if created:
    u.set_password(password)
    u.save()

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

print("created" if created or profile_created else "exists")
