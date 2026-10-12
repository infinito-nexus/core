# nocheck: mirrored-unit-test - runs inside `manage.py shell`, against the live
# Django user model and database; there is nothing to exercise outside it
"""Bring the Taiga superuser in line with what the deployment declares.

Read on stdin by ``manage.py shell``, which execs it when stdin is not a tty.

Env (from the container):
    TAIGA_SUPERUSER_NAME      login to upsert
    TAIGA_SUPERUSER_EMAIL     address the account must carry
    DJANGO_SUPERUSER_PASSWORD password it must accept afterwards

Prints ``CHANGED=1`` when it wrote anything, ``CHANGED=0`` when the account
already matched.
"""

import os

from django.contrib.auth import get_user_model

name = os.environ["TAIGA_SUPERUSER_NAME"]
email = os.environ["TAIGA_SUPERUSER_EMAIL"]
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]

User = get_user_model()
user, created = User.objects.get_or_create(username=name)

before = (user.email, user.is_staff, user.is_superuser, user.is_active)
user.email = email
user.is_staff = True
user.is_superuser = True
user.is_active = True
after = (user.email, user.is_staff, user.is_superuser, user.is_active)

needs_password = not user.check_password(password)
if needs_password:
    user.set_password(password)

user.save()
print("CHANGED=1" if created or before != after or needs_password else "CHANGED=0")
