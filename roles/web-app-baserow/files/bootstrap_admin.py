import os

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

print("created" if created else "exists")
