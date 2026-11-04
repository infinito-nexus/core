# nocheck: file-size  the deploy hands this file to `python3 -c` inside the Semaphore container, which holds no sibling module to import
"""Converge the Semaphore projects that control the applications of a host.

Reads one JSON document from standard input:
    url: the Semaphore API root, e.g. ``http://127.0.0.1:3000/api``.
    token: the bearer token the deploy minted for this run.
    project: the project name.
    key: ``name`` (ends in the fingerprint of the key), ``prefix`` (shared by
        every key this script ever stored), ``login`` and ``private_key``.
    hosts: the hosts the templates act on.
    known_hosts: the ``known_hosts`` lines pinning the host key of every host.
    inventory: the inventory name.
    repository: ``name`` and ``path``, the directory of the script in the runner.
    environment: the environment name.
    playbook: the script the templates run, relative to the repository.
    applications: the ids of the applications under app control on the host.
    deploy: present only when the inventory declares a foreign deploy:
        project: the name of the administrator-only deploy project.
        key: the deploy SSH key, shaped like ``key`` above.
        repository: ``name``, ``url``, ``branch`` and ``key`` (shaped like
            ``key`` above) of the inventory repository.
        inventory: the inventory name, which carries the deploy key.
        environment: ``prefix`` (the name ends in a digest of the rest),
            ``login``, ``known_hosts`` and ``vault_password``.
        task_template: ``name``, ``app`` and ``playbook``, the inventory
            file relative to the repository.

Output:
    One ``CHANGED <what>`` line per write, ``UNCHANGED`` when nothing was
    written. Exit code 1 with the refused request on standard error.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request

ALL = "all"
ACTIONS = ("stop", "start")
APP = "bash"
READY_ATTEMPTS = 60
READY_DELAY = 5
TIMEOUT = 30
EMPTY_JSON = "{}"
DIGEST_CHARS = 12
DEPLOY_VAULT_ENV = "DEPLOY_VAULT_PASSWORD"
DEPLOY_LOGIN_ENV = "DEPLOY_LOGIN"
DEPLOY_KNOWN_HOSTS_ENV = "DEPLOY_KNOWN_HOSTS"


class ApiError(Exception):
    """A request the Semaphore API refused."""


class Api:
    """A bearer-token client of the Semaphore API.

    Args:
        root: the API root URL.
        token: the bearer token.
        opener: ``urllib.request.urlopen`` or a stand-in.
    """

    def __init__(self, root, token, opener=urllib.request.urlopen):
        self.root = root.rstrip("/")
        self.token = token
        self.opener = opener

    def call(self, method, path, body=None):
        """Return the decoded answer of one request, None for an empty answer.

        Args:
            method: the HTTP method.
            path: the path below the API root.
            body: the JSON body, None to send none.
        """
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.root + path, data=data, method=method)  # noqa: S310 - fixed internal Semaphore API root from the converger input
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener(request, timeout=TIMEOUT) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            raise ApiError(f"{method} {path}: HTTP {error.code} {detail}") from error
        return json.loads(payload) if payload.strip() else None


def wait_until_ready(api, attempts, delay, sleep):
    """Return the projects once the API answers the deploy token.

    Args:
        api: the client.
        attempts: how often to ask before giving up.
        delay: seconds between two attempts.
        sleep: ``time.sleep`` or a stand-in.
    """
    for attempt in range(1, attempts + 1):
        try:
            return api.call("GET", "/projects")
        except OSError:
            if attempt == attempts:
                raise
            sleep(delay)
    raise ApiError("the Semaphore API never answered")


def differs(existing, desired):
    """Return whether an object lacks one of the desired field values.

    Args:
        existing: the object the API returned.
        desired: the fields it has to carry.
    """
    return any(existing.get(field) != value for field, value in desired.items())


def matches(existing, desired):
    """Return whether an object carries every desired field value.

    Args:
        existing: the object the API returned.
        desired: the fields it has to carry.
    """
    return not differs(existing, desired)


def ensure_project(api, name, projects, changes):
    """Return the id of the project, creating it when it is missing.

    Args:
        api: the client.
        name: the project name.
        projects: every project the API returned.
        changes: the change log this call appends to.
    """
    for project in projects:
        if project["name"] == name:
            return project["id"]
    created = api.call("POST", "/projects", {"name": name})
    changes.append(f"project {name} created")
    return created["id"]


def ensure_ssh_key(api, project_id, key, changes):
    """Return the id of the SSH key, storing it when no key carries its name.

    Args:
        api: the client.
        project_id: the project.
        key: ``name``, ``login`` and ``private_key``.
        changes: the change log this call appends to.
    """
    for existing in api.call("GET", f"/project/{project_id}/keys"):
        if existing["type"] == "ssh" and existing["name"] == key["name"]:
            return existing["id"]
    private_key = key["private_key"].rstrip("\n") + "\n"
    created = api.call(
        "POST",
        f"/project/{project_id}/keys",
        {
            "name": key["name"],
            "type": "ssh",
            "project_id": project_id,
            "ssh": {
                "login": key["login"],
                "passphrase": "",
                "private_key": private_key,
            },
        },
    )
    changes.append(f"key {key['name']} created")
    return created["id"]


def ensure_none_key(api, project_id, changes):
    """Return the id of the project's empty key, which a local repository needs.

    Args:
        api: the client.
        project_id: the project.
        changes: the change log this call appends to.
    """
    for existing in api.call("GET", f"/project/{project_id}/keys"):
        if existing["type"] == "none":
            return existing["id"]
    created = api.call(
        "POST",
        f"/project/{project_id}/keys",
        {"name": "None", "type": "none", "project_id": project_id},
    )
    changes.append("key None created")
    return created["id"]


def ensure_resource(api, project_id, collection, desired, same, changes):
    """Return the id of a named project resource, creating or updating it.

    Args:
        api: the client.
        project_id: the project.
        collection: the API collection, e.g. ``inventory``.
        desired: the full body the resource has to match.
        same: tells whether an existing object already matches ``desired``.
        changes: the change log this call appends to.
    """
    path = f"/project/{project_id}/{collection}"
    for existing in api.call("GET", path):
        if existing["name"] != desired["name"]:
            continue
        if not same(existing, desired):
            api.call(
                "PUT", f"{path}/{existing['id']}", {**desired, "id": existing["id"]}
            )
            changes.append(f"{collection} {desired['name']} updated")
        return existing["id"]
    created = api.call("POST", path, desired)
    changes.append(f"{collection} {desired['name']} created")
    return created["id"]


def same_environment(existing, desired):
    """Return whether an environment carries the desired variables.

    Args:
        existing: the environment the API returned.
        desired: the body the environment has to match.
    """
    return json.loads(existing.get("env") or EMPTY_JSON) == json.loads(
        desired["env"]
    ) and json.loads(existing.get("json") or EMPTY_JSON) == json.loads(desired["json"])


def inventory_content(hosts, login):
    """Return the static inventory listing every host under the app-control login.

    Args:
        hosts: the hosts the templates act on.
        login: the account the runner signs in as.
    """
    lines = ["[app_control]", *(f"{host} ansible_user={login}" for host in hosts)]
    return "\n".join(lines) + "\n"


def environment_variables(hosts, login, known_hosts):
    """Return the variables the template script reads.

    Args:
        hosts: the hosts the templates act on.
        login: the account the runner signs in as.
        known_hosts: the ``known_hosts`` lines pinning their host keys.
    """
    return {
        "APP_CONTROL_TARGETS": " ".join(f"{login}@{host}" for host in hosts),
        "APP_CONTROL_KNOWN_HOSTS": "\n".join(known_hosts),
    }


def desired_templates(applications):
    """Return name and arguments of every template, the ``all`` pair last.

    Args:
        applications: the ids of the applications under app control.
    """
    targets = [*sorted(set(applications)), ALL]
    return [
        {"name": f"{action} {target}", "arguments": [action, target]}
        for target in targets
        for action in ACTIONS
    ]


def template_body(project_id, spec, app, playbook, refs):
    """Return the full body of one template.

    Args:
        project_id: the project.
        spec: ``name`` and ``arguments`` from :func:`desired_templates`.
        app: the Semaphore app that runs the template.
        playbook: the script the template runs.
        refs: ids of the ``inventory``, ``repository`` and ``environment``.
    """
    return {
        "project_id": project_id,
        "name": spec["name"],
        "app": app,
        "playbook": playbook,
        "arguments": json.dumps(spec["arguments"]),
        "inventory_id": refs["inventory"],
        "repository_id": refs["repository"],
        "environment_id": refs["environment"],
        "environment_ids": [refs["environment"]],
        "type": "",
        "allow_override_args_in_task": False,
    }


def same_template(existing, body):
    """Return whether a template already runs what ``body`` describes.

    Args:
        existing: the template the API returned.
        body: the body from :func:`template_body`.
    """
    return (
        existing.get("app") == body["app"]
        and existing.get("playbook") == body["playbook"]
        and json.loads(existing.get("arguments") or "null")
        == json.loads(body["arguments"])
        and existing.get("inventory_id") == body["inventory_id"]
        and existing.get("repository_id") == body["repository_id"]
        and sorted(existing.get("environment_ids") or []) == body["environment_ids"]
        and (existing.get("type") or "") == body["type"]
        and bool(existing.get("allow_override_args_in_task"))
        == body["allow_override_args_in_task"]
    )


def ensure_templates(api, project_id, specs, playbook, refs, changes):
    """Converge the templates this script owns with ``specs``.

    A template is owned when it runs ``playbook`` from the owned repository;
    owned templates outside ``specs`` belong to applications the host no
    longer holds and are removed.

    Args:
        api: the client.
        project_id: the project.
        specs: the result of :func:`desired_templates`.
        playbook: the script the templates run.
        refs: ids of the ``inventory``, ``repository`` and ``environment``.
        changes: the change log this call appends to.
    """
    path = f"/project/{project_id}/templates"
    owned = {
        template["name"]: template
        for template in api.call("GET", path)
        if template.get("repository_id") == refs["repository"]
        and template.get("playbook") == playbook
    }
    wanted = set()
    for spec in specs:
        body = template_body(project_id, spec, APP, playbook, refs)
        wanted.add(spec["name"])
        current = owned.get(spec["name"])
        if current is None:
            api.call("POST", path, body)
            changes.append(f"template {spec['name']} created")
        elif not same_template(current, body):
            api.call("PUT", f"{path}/{current['id']}", {**body, "id": current["id"]})
            changes.append(f"template {spec['name']} updated")
    for name in sorted(set(owned) - wanted):
        api.call("DELETE", f"{path}/{owned[name]['id']}")
        changes.append(f"template {name} removed")


def prune_keys(api, project_id, prefix, keep, changes):
    """Remove every SSH key an earlier credential left behind.

    Args:
        api: the client.
        project_id: the project.
        prefix: the start every key name of this script shares.
        keep: the id of the key in use.
        changes: the change log this call appends to.
    """
    for key in api.call("GET", f"/project/{project_id}/keys"):
        if (
            key["id"] != keep
            and key["type"] == "ssh"
            and key["name"].startswith(prefix)
        ):
            api.call("DELETE", f"/project/{project_id}/keys/{key['id']}")
            changes.append(f"key {key['name']} removed")


def prune_environments(api, project_id, prefix, keep, changes):
    """Remove every environment an earlier vault password or host pin left behind.

    Args:
        api: the client.
        project_id: the project.
        prefix: the start every environment name of this script shares.
        keep: the id of the environment in use.
        changes: the change log this call appends to.
    """
    for environment in api.call("GET", f"/project/{project_id}/environment"):
        if environment["id"] != keep and environment["name"].startswith(prefix):
            api.call("DELETE", f"/project/{project_id}/environment/{environment['id']}")
            changes.append(f"environment {environment['name']} removed")


def deploy_environment(project_id, environment, deploy_key):
    """Return the body of the deploy environment, named after a digest of its content.

    Args:
        project_id: the project.
        environment: ``prefix``, ``login``, ``known_hosts`` and ``vault_password``.
        deploy_key: the private deploy key, which keys the digest.
    """
    variables = {
        DEPLOY_LOGIN_ENV: environment["login"],
        DEPLOY_KNOWN_HOSTS_ENV: "\n".join(environment["known_hosts"]),
    }
    digest = hmac.new(
        deploy_key.encode("utf-8"),
        json.dumps([environment["vault_password"], variables], sort_keys=True).encode(
            "utf-8"
        ),
        hashlib.sha256,
    ).hexdigest()[:DIGEST_CHARS]
    return {
        "name": f"{environment['prefix']}{digest}",
        "project_id": project_id,
        "json": EMPTY_JSON,
        "env": json.dumps(variables, sort_keys=True),
        "password": None,
        "secrets": [
            {
                "type": "env",
                "name": DEPLOY_VAULT_ENV,
                "secret": environment["vault_password"],
                "operation": "create",
            }
        ],
    }


def converge_deploy(api, deploy, projects, changes):
    """Converge the administrator-only project that deploys from an inventory repository.

    Args:
        api: the client.
        deploy: the ``deploy`` part of the standard input document.
        projects: every project the API returned.
        changes: the change log this call appends to.
    """
    project_id = ensure_project(api, deploy["project"], projects, changes)
    key_id = ensure_ssh_key(api, project_id, deploy["key"], changes)
    repository = deploy["repository"]
    repository_key_id = ensure_ssh_key(api, project_id, repository["key"], changes)
    environment = deploy_environment(
        project_id, deploy["environment"], deploy["key"]["private_key"]
    )
    refs = {
        "inventory": ensure_resource(
            api,
            project_id,
            "inventory",
            {
                "name": deploy["inventory"],
                "project_id": project_id,
                "inventory": "",
                "ssh_key_id": key_id,
                "become_key_id": None,
                "type": "static",
            },
            matches,
            changes,
        ),
        "repository": ensure_resource(
            api,
            project_id,
            "repositories",
            {
                "name": repository["name"],
                "project_id": project_id,
                "git_url": repository["url"],
                "git_branch": repository["branch"],
                "ssh_key_id": repository_key_id,
            },
            matches,
            changes,
        ),
        "environment": ensure_resource(
            api,
            project_id,
            "environment",
            environment,
            lambda existing, desired: True,
            changes,
        ),
    }
    template = deploy["task_template"]
    ensure_resource(
        api,
        project_id,
        "templates",
        template_body(
            project_id,
            {"name": template["name"], "arguments": []},
            template["app"],
            template["playbook"],
            refs,
        ),
        same_template,
        changes,
    )
    prune_keys(api, project_id, deploy["key"]["prefix"], key_id, changes)
    prune_keys(api, project_id, repository["key"]["prefix"], repository_key_id, changes)
    prune_environments(
        api, project_id, deploy["environment"]["prefix"], refs["environment"], changes
    )


def converge(api, spec, sleep):
    """Converge the whole project and return its change log.

    Args:
        api: the client.
        spec: the standard input document.
        sleep: ``time.sleep`` or a stand-in.
    """
    changes = []
    projects = wait_until_ready(api, READY_ATTEMPTS, READY_DELAY, sleep)
    project_id = ensure_project(api, spec["project"], projects, changes)
    key_id = ensure_ssh_key(api, project_id, spec["key"], changes)
    none_key_id = ensure_none_key(api, project_id, changes)
    login = spec["key"]["login"]
    refs = {
        "inventory": ensure_resource(
            api,
            project_id,
            "inventory",
            {
                "name": spec["inventory"],
                "project_id": project_id,
                "inventory": inventory_content(spec["hosts"], login),
                "ssh_key_id": key_id,
                "become_key_id": None,
                "type": "static",
            },
            lambda existing, desired: not differs(existing, desired),
            changes,
        ),
        "repository": ensure_resource(
            api,
            project_id,
            "repositories",
            {
                "name": spec["repository"]["name"],
                "project_id": project_id,
                "git_url": spec["repository"]["path"],
                "git_branch": "",
                "ssh_key_id": none_key_id,
            },
            lambda existing, desired: not differs(existing, desired),
            changes,
        ),
        "environment": ensure_resource(
            api,
            project_id,
            "environment",
            {
                "name": spec["environment"],
                "project_id": project_id,
                "json": EMPTY_JSON,
                "env": json.dumps(
                    environment_variables(spec["hosts"], login, spec["known_hosts"]),
                    sort_keys=True,
                ),
                "password": None,
                "secrets": [],
            },
            same_environment,
            changes,
        ),
    }
    ensure_templates(
        api,
        project_id,
        desired_templates(spec["applications"]),
        spec["playbook"],
        refs,
        changes,
    )
    prune_keys(api, project_id, spec["key"]["prefix"], key_id, changes)
    if "deploy" in spec:
        converge_deploy(api, spec["deploy"], projects, changes)
    return changes


def main(stdin=sys.stdin, opener=urllib.request.urlopen, sleep=time.sleep):
    """Run the convergence and return the exit code.

    Args:
        stdin: the stream carrying the input document.
        opener: ``urllib.request.urlopen`` or a stand-in.
        sleep: ``time.sleep`` or a stand-in.
    """
    spec = json.load(stdin)
    api = Api(spec["url"], spec["token"], opener)
    try:
        changes = converge(api, spec, sleep)
    except ApiError as error:
        print(f"semaphore project: {error}", file=sys.stderr)
        return 1
    for change in changes:
        print(f"CHANGED {change}")
    if not changes:
        print("UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
