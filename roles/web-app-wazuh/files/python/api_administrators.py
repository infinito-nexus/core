"""Grant the Wazuh API administrator role to the platform's administrator backend roles.

Environment:
    API_USERNAME: Wazuh API account name, set in the wazuh.manager container.
    API_PASSWORD: Wazuh API account password, set in the wazuh.manager container.
    WAZUH_RBAC_RULE_NAME: Name of the security rule this script owns.
    WAZUH_RBAC_BACKEND_ROLES: JSON list of backend roles that receive the administrator role.

Prints CHANGED when the rule or its link to the administrator role was written, OK otherwise.
"""

import base64
import json
import os
import ssl
import urllib.request

API = "https://localhost:55000"
ADMINISTRATOR = "administrator"


def call(method, path, token=None, body=None, auth=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{API}{path}", method=method, data=data)  # noqa: S310 - API is a module constant, so the scheme is always https
    request.add_header("Content-Type", "application/json")
    if auth is not None:
        request.add_header(
            "Authorization", "Basic " + base64.b64encode(auth.encode()).decode()
        )
    else:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(  # noqa: S310 - API is a module constant, so the scheme is always https
        request,
        context=ssl._create_unverified_context(),  # noqa: S323 - the Wazuh API answers on loopback inside the container this script is exec'd into, where its self-signed certificate has no issuer to verify and no path to intercept
    ) as response:
        return json.loads(response.read())["data"]


def items(path, token):
    return call("GET", f"{path}?limit=500", token)["affected_items"]


def main():
    name = os.environ["WAZUH_RBAC_RULE_NAME"]
    rule = {
        "OR": [
            {"FIND": {"backend_roles": role}}
            for role in json.loads(os.environ["WAZUH_RBAC_BACKEND_ROLES"])
        ]
    }
    token = call(
        "POST",
        "/security/user/authenticate",
        auth=f"{os.environ['API_USERNAME']}:{os.environ['API_PASSWORD']}",
    )["token"]
    changed = False
    current = next(
        (item for item in items("/security/rules", token) if item["name"] == name), None
    )
    if current is None:
        current = call("POST", "/security/rules", token, {"name": name, "rule": rule})[
            "affected_items"
        ][0]
        changed = True
    elif current["rule"] != rule:
        call("PUT", f"/security/rules/{current['id']}", token, {"rule": rule})
        changed = True
    role = next(
        item
        for item in items("/security/roles", token)
        if item["name"] == ADMINISTRATOR
    )
    if current["id"] not in role["rules"]:
        call(
            "POST",
            f"/security/roles/{role['id']}/rules?rule_ids={current['id']}",
            token,
        )
        changed = True
    print("CHANGED" if changed else "OK")


if __name__ == "__main__":
    main()
