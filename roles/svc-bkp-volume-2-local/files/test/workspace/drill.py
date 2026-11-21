"""
Args:
    workspace <apply|destroy> <workspace> <result>: runs the ``workspace``
        template of Semaphore's workspaces project; apply writes the result
        line it prints to ``result``.
    task <result> <template> <output>: runs that template of the workspace
        project ``result`` names with the order ``BKP_TEST_WORKSPACE_ORDER``
        holds and writes the task output to ``output``.
    state <workspace> ...: prints, as one JSON object, what the restore must
        bring back: OpenBao's seal state, the Gitea repositories, the Keycloak
        organizations and groups, and the object versions of the SeaweedFS
        buckets of those workspaces.
    sealed: prints OpenBao's ``sealed`` flag, ``null`` when it does not
        answer.
    check <before> <after>: prints one line per proof and exits 1 when one
        fails.

Env:
    BKP_TEST_HEALTH_TIMEOUT, BKP_TEST_REPO_ROOT, BKP_TEST_WORKSPACE_ORDER,
    BKP_TEST_SEMAPHORE_URL, BKP_TEST_SEMAPHORE_USERNAME_B64,
    BKP_TEST_SEMAPHORE_PASSWORD_B64, BKP_TEST_OPENBAO_URL, BKP_TEST_GITEA_URL,
    BKP_TEST_GITEA_ORGANIZATION, BKP_TEST_GITEA_BASIC_AUTH_B64,
    BKP_TEST_KEYCLOAK_URL, BKP_TEST_KEYCLOAK_REALM,
    BKP_TEST_KEYCLOAK_ADMIN_REALM, BKP_TEST_KEYCLOAK_CLIENT_ID,
    BKP_TEST_KEYCLOAK_USERNAME_B64, BKP_TEST_KEYCLOAK_PASSWORD_B64,
    BKP_TEST_SEAWEEDFS_URL, BKP_TEST_SEAWEEDFS_REGION,
    BKP_TEST_SEAWEEDFS_ACCESS_KEY_B64, BKP_TEST_SEAWEEDFS_SECRET_KEY_B64.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
from pathlib import Path

POLL_SECONDS = 5
TERMINAL = ("success", "error", "stopped")
WORKSPACE_TEMPLATE = "workspace"
PAGE = 50


class DrillError(Exception):
    pass


def secret(name):
    """
    Args:
        name: an env var holding a base64 value.

    Returns:
        The decoded value; never printed.
    """
    return base64.b64decode(os.environ[name]).decode("utf-8")


def request(method, url, headers=None, body=None):
    """
    Args:
        method: HTTP verb.
        url: an https URL.
        headers: request headers.
        body: request body bytes.

    Returns:
        ``(status, headers, body)``.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise DrillError(
            f"refusing the non-https endpoint {parts.scheme}://{parts.netloc}"
        )
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    connection = http.client.HTTPSConnection(
        parts.netloc,
        timeout=int(os.environ["BKP_TEST_HEALTH_TIMEOUT"]),
        context=ssl.create_default_context(),
    )
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    finally:
        connection.close()


def fetch_json(method, url, headers, payload=None):
    """
    Args:
        method: HTTP verb.
        url: an https URL.
        headers: request headers.
        payload: a JSON-serialisable body.

    Returns:
        The decoded answer, ``None`` for an empty one.
    """
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    status, _, raw = request(
        method, url, {**headers, "Content-Type": "application/json"}, body
    )
    if status >= 300:
        raise DrillError(
            f"{method} {urllib.parse.urlsplit(url).path} answered {status}"
        )
    return json.loads(raw) if raw else None


class Semaphore:
    def __init__(self):
        self.base = os.environ["BKP_TEST_SEMAPHORE_URL"].rstrip("/")
        login = {
            "auth": secret("BKP_TEST_SEMAPHORE_USERNAME_B64"),
            "password": secret("BKP_TEST_SEMAPHORE_PASSWORD_B64"),
        }
        status, headers, _ = request(
            "POST",
            f"{self.base}/api/auth/login",
            {"Content-Type": "application/json"},
            json.dumps(login).encode("utf-8"),
        )
        if status != 204:
            raise DrillError(f"Semaphore refused the login with {status}")
        cookies = [
            value.split(";", 1)[0] for value in headers.get_all("Set-Cookie") or []
        ]
        self.headers = {"Cookie": "; ".join(cookies)}

    def call(self, method, path, payload=None):
        """
        Args:
            method: HTTP verb.
            path: the API path below ``/api``.
            payload: a JSON-serialisable body.

        Returns:
            The decoded answer.
        """
        return fetch_json(method, f"{self.base}/api{path}", self.headers, payload)

    def workspace_template(self):
        """
        Returns:
            ``(project_id, template_id)`` of the ``workspace`` template.
        """
        for project in self.call("GET", "/projects"):
            for template in self.call("GET", f"/project/{project['id']}/templates"):
                if template["name"] == WORKSPACE_TEMPLATE:
                    return project["id"], template["id"]
        raise DrillError("no Semaphore project holds the workspace template")

    def run(self, project_id, template_id, variables, output):
        """
        Args:
            project_id: the Semaphore project.
            template_id: the template to run.
            variables: the survey values.
            output: where the task output lands, mode 0600.

        Returns:
            ``(succeeded, output lines)``.
        """
        task = self.call(
            "POST",
            f"/project/{project_id}/tasks",
            {"template_id": template_id, "environment": json.dumps(variables)},
        )
        path = f"/project/{project_id}/tasks/{task['id']}"
        deadline = time.monotonic() + int(os.environ["BKP_TEST_HEALTH_TIMEOUT"])
        while (status := self.call("GET", path)["status"]) not in TERMINAL:
            if time.monotonic() >= deadline:
                raise DrillError(f"task {task['id']} still {status} at the deadline")
            time.sleep(POLL_SECONDS)
        lines = [entry["output"] for entry in self.call("GET", f"{path}/output")]
        target = Path(output)
        target.touch(mode=0o600)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return status == "success", lines


def workspace(action, workspace_id, result):
    api = Semaphore()
    project_id, template_id = api.workspace_template()
    variables = {"WORKSPACE": workspace_id, "WORKSPACE_ACTION": action}
    if action == "apply":
        variables["WORKSPACE_CORE_VERSION"] = "latest"
        variables["WORKSPACE_PLATFORM_TOKENS"] = "true"
    succeeded, lines = api.run(project_id, template_id, variables, f"{result}.log")
    if not succeeded:
        raise DrillError(
            f"workspace {action} of {workspace_id} failed, see {result}.log"
        )
    if action == "apply":
        written = json.loads(lines[-1])
        if written.get("workspace") != workspace_id:
            raise DrillError(
                f"workspace apply of {workspace_id} printed another result"
            )
        Path(result).write_text(json.dumps(written), encoding="utf-8")


def task(result, template, output):
    entry = json.loads(Path(result).read_text(encoding="utf-8"))["templates"][template]
    order = json.loads(os.environ["BKP_TEST_WORKSPACE_ORDER"])
    succeeded, _ = Semaphore().run(
        entry["project_id"], entry["template_id"], order, output
    )
    if not succeeded:
        raise DrillError(f"the {template} task failed, see {output}")


def sealed():
    """
    Returns:
        OpenBao's ``sealed`` flag, ``None`` when it does not answer.
    """
    base = os.environ["BKP_TEST_OPENBAO_URL"].rstrip("/")
    try:
        status, _, raw = request("GET", f"{base}/v1/sys/seal-status")
    except OSError:
        return None
    return json.loads(raw)["sealed"] if status == 200 else None


def repositories(workspaces):
    base = os.environ["BKP_TEST_GITEA_URL"].rstrip("/")
    organization = os.environ["BKP_TEST_GITEA_ORGANIZATION"]
    auth = base64.b64encode(secret("BKP_TEST_GITEA_BASIC_AUTH_B64").encode("utf-8"))
    headers = {"Authorization": f"Basic {auth.decode('ascii')}"}
    names, page = [], 1
    while batch := fetch_json(
        "GET",
        f"{base}/api/v1/orgs/{organization}/repos?limit={PAGE}&page={page}",
        headers,
    ):
        names.extend(repo["full_name"] for repo in batch)
        page += 1
    return {ws: sorted(name for name in names if ws in name) for ws in workspaces}


def organizations(workspaces):
    base = os.environ["BKP_TEST_KEYCLOAK_URL"].rstrip("/")
    realm = os.environ["BKP_TEST_KEYCLOAK_REALM"]
    form = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": os.environ["BKP_TEST_KEYCLOAK_CLIENT_ID"],
            "username": secret("BKP_TEST_KEYCLOAK_USERNAME_B64"),
            "password": secret("BKP_TEST_KEYCLOAK_PASSWORD_B64"),
        }
    ).encode("utf-8")
    admin_realm = os.environ["BKP_TEST_KEYCLOAK_ADMIN_REALM"]
    status, _, raw = request(
        "POST",
        f"{base}/realms/{admin_realm}/protocol/openid-connect/token",
        {"Content-Type": "application/x-www-form-urlencoded"},
        form,
    )
    if status != 200:
        raise DrillError(f"Keycloak refused the admin token with {status}")
    headers = {"Authorization": f"Bearer {json.loads(raw)['access_token']}"}
    admin = f"{base}/admin/realms/{realm}"
    state = {}
    for ws in workspaces:
        found = fetch_json("GET", f"{admin}/organizations?search={ws}", headers)
        groups, pending = [], fetch_json("GET", f"{admin}/groups?search={ws}", headers)
        while pending:
            group = pending.pop()
            groups.append(group["path"])
            pending.extend(group.get("subGroups") or [])
        state[ws] = {
            "organizations": sorted(org["alias"] for org in found),
            "groups": sorted(groups),
        }
    return state


def versions(workspaces):
    sys.path.insert(
        0,
        str(
            Path(os.environ["BKP_TEST_REPO_ROOT"])
            / "roles/web-svc-seaweedfs/files/test"
        ),
    )
    import sigv4

    base = urllib.parse.urlsplit(os.environ["BKP_TEST_SEAWEEDFS_URL"])
    keys = {
        "region": os.environ["BKP_TEST_SEAWEEDFS_REGION"],
        "access_key": secret("BKP_TEST_SEAWEEDFS_ACCESS_KEY_B64"),
        "secret_key": secret("BKP_TEST_SEAWEEDFS_SECRET_KEY_B64"),
    }

    def s3(path, query=None):
        headers = sigv4.sign("GET", base.netloc, path, query=query, **keys)
        suffix = f"?{sigv4.canonical_query(query)}" if query else ""
        status, _, raw = request("GET", f"https://{base.netloc}{path}{suffix}", headers)
        if status != 200:
            raise DrillError(f"SeaweedFS answered {path} with {status}")
        return raw.decode("utf-8")

    buckets = re.findall(r"<Name>([^<]+)</Name>", s3("/"))
    state = {}
    for ws in workspaces:
        state[ws] = {}
        for bucket in (name for name in buckets if ws in name):
            listing = s3(f"/{bucket}", {"versions": ""})
            if "<IsTruncated>true</IsTruncated>" in listing:
                raise DrillError(
                    f"bucket {bucket} holds more versions than one listing"
                )
            state[ws][bucket] = sorted(
                f"{key}@{version}"
                for key, version in re.findall(
                    r"<Version>.*?<Key>([^<]+)</Key>.*?<VersionId>([^<]+)</VersionId>.*?</Version>",
                    listing,
                    re.DOTALL,
                )
            )
    return state


def state(workspaces):
    return {
        "workspaces": workspaces,
        "sealed": sealed(),
        "repositories": repositories(workspaces),
        "organizations": organizations(workspaces),
        "versions": versions(workspaces),
    }


def check(before_file, after_file):
    """
    Args:
        before_file: the state recorded before the backup.
        after_file: the state recorded after the restore.

    Returns:
        The failed proofs.
    """
    before = json.loads(Path(before_file).read_text(encoding="utf-8"))
    after = json.loads(Path(after_file).read_text(encoding="utf-8"))
    failed = []
    if after["sealed"] is False:
        print("workspace drill: OpenBao unseals with the inventory's seal key")
    else:
        failed.append(f"OpenBao reports sealed={after['sealed']} after the restore")
    proofs = (
        (
            "SeaweedFS serves every object version of",
            "versions",
            lambda held: any(held.values()),
        ),
        ("Gitea serves the repository of", "repositories", bool),
        (
            "Keycloak holds the organization and groups of",
            "organizations",
            lambda held: bool(held["organizations"] and held["groups"]),
        ),
    )
    for ws in before["workspaces"]:
        for label, key, filled in proofs:
            held = before[key][ws]
            if not filled(held):
                failed.append(f"{key} of {ws} was empty before the backup")
            elif after[key][ws] != held:
                failed.append(f"{key} of {ws} differ after the restore")
            else:
                print(f"workspace drill: {label} {ws}")
    return failed


def main(argv):
    """
    Args:
        argv: the command line after the script name.

    Returns:
        The exit code.
    """
    try:
        if (
            argv[:1] == ["workspace"]
            and len(argv) == 4
            and argv[1] in ("apply", "destroy")
        ):
            workspace(argv[1], argv[2], argv[3])
        elif argv[:1] == ["task"] and len(argv) == 4:
            task(argv[1], argv[2], argv[3])
        elif argv[:1] == ["state"] and len(argv) > 1:
            print(json.dumps(state(argv[1:]), sort_keys=True))
        elif argv == ["sealed"]:
            print(json.dumps(sealed()))
        elif argv[:1] == ["check"] and len(argv) == 3:
            failed = check(argv[1], argv[2])
            for line in failed:
                print(f"FAIL: workspace drill: {line}")
            return 1 if failed else 0
        else:
            print(f"drill.py: unexpected arguments {argv}", file=sys.stderr)
            return 2
    except DrillError as error:
        print(f"FAIL: workspace drill: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
