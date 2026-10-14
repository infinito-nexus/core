"""Print the API token Weblate issued to its administrator.

The token lives in Weblate's own database and only its management shell can
reach it. The deploy reads it here and hands it to the translation gateway,
which otherwise renders an empty bearer and lets a machine engine overwrite
reviewed strings.

Fed to ``weblate shell`` on stdin. The username arrives in the environment
with no default: reading the token of the wrong account would be worse than
failing.
"""

import os

from weblate.auth.models import User

print(User.objects.get(username=os.environ["WEBLATE_ADMIN_USERNAME"]).auth_token.key)
