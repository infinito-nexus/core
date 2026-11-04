import os

from funkwhale_api.users.models import User

user = User.objects.filter(username=os.environ["FUNKWHALE_ADMIN_USERNAME"]).first()
if user is None:
    state = "MISSING"
elif (
    user.is_active
    and user.is_staff
    and user.is_superuser
    and user.check_password(os.environ["FUNKWHALE_ADMIN_PASSWORD"])
):
    state = "OK"
else:
    state = "DRIFT"
print("FUNKWHALE_ADMIN=" + state)
