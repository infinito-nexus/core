"""
Environment:
    MEMBER:      realm username whose membership changes.
    METHOD:      PUT grants the group, DELETE revokes it.
    GROUP_PATH:  Keycloak path of the group.

Runs inside the broker with its own KEYCLOAK_* settings, because curl refuses
to resolve the .onion Keycloak URL of a Tor deployment.
"""

import os
import sys

sys.path.insert(0, "/opt/broker")

from access import Keycloak

keycloak = Keycloak(
    os.environ["KEYCLOAK_URL"],
    os.environ["KEYCLOAK_REALM"],
    os.environ["KEYCLOAK_ADMIN_USERNAME"],
    os.environ["KEYCLOAK_ADMIN_PASSWORD"],
    0,
    60,
)
users = keycloak._get("/users", {"username": os.environ["MEMBER"], "exact": "true"})
if len(users) != 1:
    sys.exit(f"{len(users)} users named {os.environ['MEMBER']}")
group = keycloak._get(f"/group-by-path{os.environ['GROUP_PATH']}", {})
status, body = keycloak._request(
    os.environ["METHOD"],
    f"{keycloak.base_url}/admin/realms/{keycloak.realm}/users/{users[0]['id']}/groups/{group['id']}",
    headers={"Authorization": f"Bearer {keycloak._admin_token()}"},
)
if status >= 300 and status != 404:
    sys.exit(f"{os.environ['METHOD']} {os.environ['GROUP_PATH']} -> {status} {body}")
