# nocheck: file-size  the deploy hands this file to `python3 -c` inside the Semaphore container, which holds no sibling module to import
"""Converge the Semaphore projects of the platform and of its workspaces.

Reads one JSON document from standard input:
    url: the Semaphore API root, e.g. ``http://127.0.0.1:3000/api``.
    token: the bearer token the deploy minted for this run.
    project: the project name.
    runner_tag: the tag of the project's runner.
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
        runner_tag: the tag of the deploy project's runner.
        key: the deploy SSH key, shaped like ``key`` above.
        repository: ``name``, ``url``, ``branch`` and ``key`` (shaped like
            ``key`` above) of the inventory repository.
        inventory: the inventory name, which carries the deploy key.
        environment: ``prefix`` (the name ends in a digest of the rest),
            ``login``, ``known_hosts`` and ``vault_password``.
        task_template: ``name``, ``app`` and ``playbook``, the inventory
            file relative to the repository.
    workspaces: present only beside ``deploy``, see :func:`converge_workspaces`.
    workspace: replaces every key but ``url`` and ``token`` for one workspace
        operation, see :func:`apply_workspace` and :func:`destroy_workspace`.

Output:
    One ``CHANGED <what>`` line per write, ``UNCHANGED`` when nothing was
    written, one ``FINDING <what>`` line per post-converge finding and, for a
    workspace operation, one ``RESULT <json>`` line. Exit code 1 with the
    refused request or the findings on standard error.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sys
import time
import urllib.error
import urllib.request

ALL = "all"
ACTIONS = ("stop", "start")
APP = "bash"
ANSIBLE_APP = "ansible"
READY_ATTEMPTS = 60
READY_DELAY = 5
STOP_TIMEOUT = 120
STOP_DELAY = 5
FINISHED_STATUSES = ("success", "error", "stopped")
TIMEOUT = 30
EMPTY_JSON = "{}"
EMPTY_LIST_JSON = "[]"
DIGEST_CHARS = 12
DEPLOY_VAULT_ENV = "DEPLOY_VAULT_PASSWORD"
DEPLOY_LOGIN_ENV = "DEPLOY_LOGIN"
DEPLOY_KNOWN_HOSTS_ENV = "DEPLOY_KNOWN_HOSTS"
JWT_AUDIENCE = "openbao"
SURVEY_TARGET = "env"
LOCKED_FLAGS = (
    "allow_override_args_in_task",
    "allow_override_branch_in_task",
    "allow_parallel_tasks",
)
CAN_RUN_PROJECT_TASKS = 1
CAN_READ_PROJECT = 128
GRANT_PERMISSIONS = CAN_RUN_PROJECT_TASKS | CAN_READ_PROJECT
GUEST = "guest"
MANAGER = "manager"
WORKSPACE_ALIAS_PREFIX = "ws-"
READ_KEY_PREFIX = "read "
HOST_KEY = "HOST_KEY"
NONE_KEY = "None"
WORKSPACE_RESOURCE = "workspace"
MEMBERS_TEMPLATE = "members"
IDENTITY_COMMAND = "workspaces-identity"
ROTATION_COMMAND = "store-rotation-identity"
EXPORT_SCHEDULE_COMMAND = "export-schedule-identity"
TASK_ENTITIES_COMMAND = "task-entities-identity"
TASK_ENTITIES_TEMPLATE = "prune task entities"
PLATFORM_KINDS = ("provision", "export")
CHECKOUT_KINDS = ("provision",)

ORDER_SURVEY = (("SALES_ORDER", True), ("LINE", True))
HOST_SURVEY = (("HOST", True), (HOST_KEY, True))
COMMIT_SURVEY = (("INVENTORY_COMMIT", True),)
WORKSPACE_TEMPLATES = (
    {
        "name": "deploy",
        "script": "deploy.sh",
        "survey": ORDER_SURVEY
        + HOST_SURVEY
        + (("ROLES", True), ("DNS_LABEL", True))
        + COMMIT_SURVEY,
    },
    {
        "name": "update",
        "script": "host.sh",
        "arguments": ["update"],
        "survey": HOST_SURVEY + COMMIT_SURVEY,
    },
    {
        "name": "backup",
        "script": "host.sh",
        "arguments": ["backup"],
        "survey": HOST_SURVEY + COMMIT_SURVEY,
    },
    {
        "name": "restart",
        "script": "host.sh",
        "arguments": ["restart"],
        "survey": HOST_SURVEY,
    },
    {
        "name": "suspend",
        "script": "host.sh",
        "arguments": ["suspend"],
        "survey": HOST_SURVEY,
    },
    {
        "name": "resume",
        "script": "host.sh",
        "arguments": ["resume"],
        "survey": HOST_SURVEY,
    },
    {
        "name": "release",
        "script": "host.sh",
        "arguments": ["release"],
        "survey": HOST_SURVEY,
    },
    {
        "name": "usage",
        "script": "usage.sh",
        "survey": (),
        "cron": "0 3 * * *",
    },
)
WORKSPACES_TEMPLATES = (
    {
        "name": "workspace",
        "script": "workspace.sh",
        "repository": "inventory",
        "survey": (
            ("WORKSPACE", True),
            ("WORKSPACE_ACTION", True),
            ("WORKSPACE_CORE_VERSION", False),
            ("WORKSPACE_TARGETS", False),
            ("WORKSPACE_PLATFORM_TOKENS", False),
        ),
    },
    {
        "name": "members",
        "script": "members.sh",
        "repository": "scripts",
        "survey": (
            ("WORKSPACE", True),
            ("MEMBERS_ACTION", True),
            ("WORKSPACE_MEMBER", False),
            ("INVITE_KEY", False),
            ("WORKSPACE_ROLE", False),
            ("WORKSPACE_SUSPENDED", True),
        ),
    },
    {
        "name": "user",
        "script": "user.sh",
        "repository": "scripts",
        "survey": (("USER_ACTION", True), ("USER_ID", True)),
    },
)
WORKSPACES_SCHEDULED_TEMPLATES = (
    {
        "name": "rotate store credentials",
        "script": "store-credentials.sh",
        "repository": "inventory",
        "survey": (),
        "cron": "0 4 * * 1",
    },
    {
        "name": TASK_ENTITIES_TEMPLATE,
        "script": "task-entities.sh",
        "repository": "scripts",
        "survey": (),
        "cron": "30 5 * * *",
    },
)
PROVIDER_SURVEY = (("PROVIDER_TOKEN", True),)
PROVISION_PROVIDERS = ("hetzner", "incus", "ionos", "proxmox", "scs")
ORDER_ACTIONS = ("provision", "destroy")
PROVISION_TEMPLATES = (
    *(
        {
            "name": f"{action}-{provider}",
            "script": f"{action}.sh",
            "arguments": [provider],
            "survey": ORDER_SURVEY + PROVIDER_SURVEY,
        }
        for action in ORDER_ACTIONS
        for provider in PROVISION_PROVIDERS
    ),
    {
        "name": "unlock",
        "script": "unlock.sh",
        "survey": ORDER_SURVEY,
    },
    {
        "name": "dns",
        "script": "dns.sh",
        "survey": (
            ("DNS_ACTION", True),
            *ORDER_SURVEY,
            ("HOST", True),
            ("DNS_LABEL", True),
        ),
    },
    {
        "name": "zone",
        "script": "zone.sh",
        "survey": (("ZONE_ACTION", True), *ORDER_SURVEY, ("DOMAIN", False)),
    },
)
EXPORT_TEMPLATES = (
    {
        "name": "export",
        "script": "export.sh",
        "survey": (("WORKSPACE", True), ("EXPORT_FOR", True)),
    },
)
EXPORT_SCHEDULED_TEMPLATES = (
    {
        "name": "announce owners",
        "script": "announce-owners.sh",
        "survey": (),
        "cron": "0 6 * * *",
    },
    {
        "name": "prune exports",
        "script": "prune-exports.sh",
        "survey": (),
        "cron": "0 * * * *",
    },
)
PROBE_TEMPLATE = {
    "name": "probe",
    "script": "probe.sh",
    "survey": (("PROBE_SCRIPT", True), ("PROBE_ARGS", False)),
}
PLATFORM_TEMPLATES = {"provision": PROVISION_TEMPLATES, "export": EXPORT_TEMPLATES}


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


def is_missing(error):
    """Args:
    error: the :class:`ApiError` of a request.

    Returns:
        Whether the request answered 404.
    """
    return ": HTTP 404" in str(error)


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
        {"name": NONE_KEY, "type": "none", "project_id": project_id},
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


def survey_var(name, required):
    """Args:
    name: the variable name.
    required: whether a task must set it.

    Returns:
        A survey variable that reaches the script as an environment variable.
    """
    return {
        "name": name,
        "title": name,
        "description": "",
        "type": "",
        "required": required,
        "target": SURVEY_TARGET,
    }


def script_template(entry, scripts):
    """Args:
    entry: one entry of ``WORKSPACE_TEMPLATES`` or its siblings.
    scripts: ``script_app`` (the app that runs a script of the runner image
        by its name), ``deploy_script``, ``deploy_app`` and ``inventory_file``.

    Returns:
        ``app``, ``playbook`` and ``arguments`` of a template that runs the
        entry's script from the runner image, its playbook relative as
        Semaphore demands.
    """
    if entry["script"] == scripts["deploy_script"]:
        return {
            "app": scripts["deploy_app"],
            "playbook": scripts["inventory_file"],
            "arguments": [],
        }
    return {
        "app": scripts["script_app"],
        "playbook": entry["script"],
        "arguments": list(entry.get("arguments", [])),
    }


def template_body(project_id, spec, refs):
    """Return the full, locked body of one template.

    Args:
        project_id: the project.
        spec: ``name``, ``app``, ``playbook``, ``arguments`` and ``survey``,
            a sequence of ``(name, required)``.
        refs: ids of the ``inventory``, ``repository`` and ``environment``,
            and the ``runner_tag`` of the project's runner.
    """
    body = {
        "project_id": project_id,
        "name": spec["name"],
        "app": spec["app"],
        "playbook": spec["playbook"],
        "arguments": json.dumps(spec["arguments"]),
        "inventory_id": refs["inventory"],
        "repository_id": refs["repository"],
        "environment_id": refs["environment"],
        "environment_ids": [refs["environment"]],
        "type": "",
        "runner_tag": refs["runner_tag"],
        "survey_vars": [
            survey_var(name, required) for name, required in spec["survey"]
        ],
        "jwt_params": {"enabled": True, "audience": JWT_AUDIENCE},
    }
    for flag in LOCKED_FLAGS:
        body[flag] = False
    if spec["app"] == ANSIBLE_APP:
        body["task_params"] = {"allow_override_inventory": False}
    return body


def lock_findings(body):
    """Args:
    body: a template body.

    Returns:
        Every field that leaves the template open to a run-time change.
    """
    findings = [flag for flag in LOCKED_FLAGS if body.get(flag) is not False]
    if not body.get("runner_tag"):
        findings.append("runner_tag")
    if _jwt(body) != (True, JWT_AUDIENCE):
        findings.append("jwt_params")
    if body.get("app") == ANSIBLE_APP and _inventory_lock(body) is not False:
        findings.append("task_params.allow_override_inventory")
    findings.extend(
        f"survey_vars.{variable.get('name')}.target"
        for variable in body.get("survey_vars") or []
        if variable.get("target") != SURVEY_TARGET
    )
    return findings


def _survey(template):
    return [
        (v.get("name"), bool(v.get("required")), v.get("target"))
        for v in template.get("survey_vars") or []
    ]


def _jwt(template):
    jwt = template.get("jwt_params") or {}
    return (jwt.get("enabled") is True, jwt.get("audience"))


def _inventory_lock(template):
    return (template.get("task_params") or {}).get("allow_override_inventory")


def same_template(existing, body):
    """Return whether a template already runs what ``body`` describes, locked as it is.

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
        and existing.get("runner_tag") == body["runner_tag"]
        and all(existing.get(flag) is False for flag in LOCKED_FLAGS)
        and _jwt(existing) == _jwt(body)
        and _survey(existing) == _survey(body)
        and (body["app"] != ANSIBLE_APP or _inventory_lock(existing) is False)
    )


def ensure_template(api, project_id, body, changes):
    """Args:
    api: the client.
    project_id: the project.
    body: the body from :func:`template_body`.
    changes: the change log this call appends to.

    Returns:
        The id of the named template, created or realigned to ``body``.
    """
    return ensure_resource(api, project_id, "templates", body, same_template, changes)


def ensure_templates(api, project_id, specs, playbook, refs, changes):
    """Converge the app-control templates this script owns with ``specs``.

    A template is owned when it runs ``playbook`` from the owned repository;
    owned templates outside ``specs`` belong to applications the host no
    longer holds and are removed.

    Args:
        api: the client.
        project_id: the project.
        specs: the result of :func:`desired_templates`.
        playbook: the script the templates run.
        refs: ids of the ``inventory``, ``repository`` and ``environment``,
            and the ``runner_tag``.
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
        body = template_body(
            project_id,
            {**spec, "app": APP, "playbook": playbook, "survey": ()},
            refs,
        )
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


def deploy_environment(project_id, environment, deploy_key, variables):
    """Return the body of the deploy environment, named after a digest of its content.

    Args:
        project_id: the project.
        environment: ``prefix``, ``login``, ``known_hosts``, ``vault_password``
            and ``secrets``, further ``{name: value}`` env secrets.
        deploy_key: the private deploy key, which keys the digest.
        variables: further plain variables of the environment.
    """
    plain = {
        DEPLOY_LOGIN_ENV: environment["login"],
        DEPLOY_KNOWN_HOSTS_ENV: "\n".join(environment["known_hosts"]),
        **{name: str(value) for name, value in variables.items()},
    }
    hidden = {
        DEPLOY_VAULT_ENV: environment["vault_password"],
        **{name: str(value) for name, value in environment["secrets"].items()},
    }
    digest = hmac.new(
        deploy_key.encode("utf-8"),
        json.dumps([plain, hidden], sort_keys=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:DIGEST_CHARS]
    return {
        "name": f"{environment['prefix']}{digest}",
        "project_id": project_id,
        "json": EMPTY_JSON,
        "env": json.dumps(plain, sort_keys=True),
        "password": None,
        "secrets": [
            {"type": "env", "name": name, "secret": value, "operation": "create"}
            for name, value in hidden.items()
        ],
    }


def find_user(api, username):
    """Args:
    api: the client.
    username: the account's username.

    Returns:
        The account object, None when it is missing.
    """
    return next(
        (user for user in api.call("GET", "/users") if user["username"] == username),
        None,
    )


def ensure_user(api, store, changes):
    """Args:
    api: the client.
    store: ``username``, ``name`` and ``email`` of the store's account.
    changes: the change log this call appends to.

    Returns:
        The id of the store's local, non-admin account, created once with a
        password nobody keeps.
    """
    user = find_user(api, store["username"])
    if user is not None:
        if user.get("admin"):
            raise ApiError(f"the store account {store['username']} is an admin")
        return user["id"]
    created = api.call(
        "POST",
        "/users",
        {
            "username": store["username"],
            "name": store["name"],
            "email": store["email"],
            "password": secrets.token_urlsafe(32),
            "external": False,
            "admin": False,
            "alert": False,
        },
    )
    changes.append(f"user {store['username']} created")
    return created["id"]


def ensure_member(api, project_id, user_id, role, changes):
    """Give one account exactly ``role`` in a project.

    Args:
        api: the client.
        project_id: the project.
        user_id: the account.
        role: the project role.
        changes: the change log this call appends to.
    """
    path = f"/project/{project_id}/users"
    for member in api.call("GET", path):
        if member["id"] != user_id:
            continue
        if member.get("role") != role:
            api.call("PUT", f"{path}/{user_id}", {"user_id": user_id, "role": role})
            changes.append(f"member {user_id} of project {project_id} set to {role}")
        return
    api.call("POST", path, {"user_id": user_id, "role": role})
    changes.append(f"member {user_id} of project {project_id} added as {role}")


def ensure_grant(api, project_id, template_id, role, changes):
    """Leave exactly one grant on a template: ``role`` with run and read.

    Args:
        api: the client.
        project_id: the project.
        template_id: the template.
        role: the project role the grant names.
        changes: the change log this call appends to.
    """
    path = f"/project/{project_id}/templates/{template_id}/perms"
    kept = False
    for grant in api.call("GET", path) or []:
        if (
            not kept
            and grant.get("role_slug") == role
            and grant.get("permissions") == GRANT_PERMISSIONS
        ):
            kept = True
            continue
        api.call("DELETE", f"{path}/{grant['id']}")
        changes.append(f"grant {grant['id']} of template {template_id} removed")
    if not kept:
        api.call(
            "POST",
            path,
            {
                "project_id": project_id,
                "template_id": template_id,
                "role_slug": role,
                "permissions": GRANT_PERMISSIONS,
            },
        )
        changes.append(f"grant {role} on template {template_id} created")


def ensure_schedule(api, project_id, template_id, entry, changes):
    """Leave exactly one active schedule on a template, running at ``entry["cron"]``.

    Args:
        api: the client.
        project_id: the project.
        template_id: the template.
        entry: one entry with a ``cron`` of ``WORKSPACE_TEMPLATES``,
            ``WORKSPACES_SCHEDULED_TEMPLATES`` or ``EXPORT_SCHEDULED_TEMPLATES``.
        changes: the change log this call appends to.
    """
    path = f"/project/{project_id}/schedules"
    desired = {
        "project_id": project_id,
        "template_id": template_id,
        "name": entry["name"],
        "cron_format": entry["cron"],
        "active": True,
    }
    held = [
        schedule
        for schedule in api.call("GET", path) or []
        if schedule.get("template_id") == template_id
    ]
    for schedule in held[1:]:
        api.call("DELETE", f"{path}/{schedule['id']}")
        changes.append(f"schedule {schedule['id']} of template {template_id} removed")
    if not held:
        api.call("POST", path, desired)
        changes.append(f"schedule of template {entry['name']} created")
    elif differs(held[0], desired):
        api.call("PUT", f"{path}/{held[0]['id']}", {**desired, "id": held[0]["id"]})
        changes.append(f"schedule of template {entry['name']} updated")


def grant_findings(api, project_id, granted, role):
    """Args:
    api: the client.
    project_id: the project.
    granted: the names of the templates that carry the grant.
    role: the project role the grant names.

    Returns:
        Every grant of the project beyond one run-and-read grant for ``role``
        on each granted template, and every granted template that is missing.
    """
    findings = []
    templates = api.call("GET", f"/project/{project_id}/templates")
    for template in templates:
        name = template["name"]
        grants = _grants(api, project_id, template)
        if name not in granted:
            findings.extend(_stray_grants(project_id, name, grants))
        else:
            findings.extend(_run_only_grant(project_id, name, grants, role))
    findings.extend(
        f"template {name} of project {project_id} is missing"
        for name in sorted(set(granted) - {t["name"] for t in templates})
    )
    return findings


def provision_grant_findings(api, project_id, entries, role):
    """Args:
    api: the client.
    project_id: the provision project.
    entries: the templates ``workspace apply`` creates there per workspace,
        each named ``<name> ws-<id>``.
    role: the project role the grant names.

    Returns:
        One finding per workspace template whose grants are not exactly one
        run-and-read grant for ``role``, and one per grant on any other
        template of the project.
    """
    kinds = {entry["name"] for entry in entries}
    findings = []
    for template in api.call("GET", f"/project/{project_id}/templates"):
        name = template["name"]
        grants = _grants(api, project_id, template)
        kind, _, alias = name.partition(" ")
        if kind in kinds and alias.startswith(WORKSPACE_ALIAS_PREFIX):
            findings.extend(_run_only_grant(project_id, name, grants, role))
        else:
            findings.extend(_stray_grants(project_id, name, grants))
    return findings


def _grants(api, project_id, template):
    return (
        api.call("GET", f"/project/{project_id}/templates/{template['id']}/perms") or []
    )


def _run_only_grant(project_id, name, grants, role):
    if [(g.get("role_slug"), g.get("permissions")) for g in grants] == [
        (role, GRANT_PERMISSIONS)
    ]:
        return []
    return [
        (
            f"template {name} of project {project_id} carries {len(grants)} grants, "
            f"expected one {role} grant with {GRANT_PERMISSIONS}"
        )
    ]


def _stray_grants(project_id, name, grants):
    return [f"template {name} of project {project_id} carries a grant" for _ in grants]


def schedule_grant_findings(api, project_id, entries):
    """Args:
    api: the client.
    project_id: the project.
    entries: the scheduled templates of the project, which only their
        schedule starts.

    Returns:
        One finding per grant on a template of ``entries``.
    """
    names = {entry["name"] for entry in entries}
    return [
        finding
        for template in api.call("GET", f"/project/{project_id}/templates")
        if template["name"] in names
        for finding in _stray_grants(
            project_id, template["name"], _grants(api, project_id, template)
        )
    ]


def member_findings(api, project_id, store_id, role, admins):
    """Args:
    api: the client.
    project_id: the project.
    store_id: the id of the store's account.
    role: the role the store holds there.
    admins: the ids of every Semaphore admin.

    Returns:
        Every member of the project beyond the store's ``role`` and the admins.
    """
    findings = []
    store_role = None
    for member in api.call("GET", f"/project/{project_id}/users"):
        if member["id"] == store_id:
            store_role = member.get("role")
        elif member["id"] not in admins:
            findings.append(
                f"account {member['id']} holds {member.get('role')} in project {project_id}"
            )
    if store_role != role:
        findings.append(
            f"the store holds {store_role} in project {project_id}, expected {role}"
        )
    return findings


def platform_refs(api, project_id, spec, changes):
    """Args:
    api: the client.
    project_id: the project.
    spec: ``key``, ``repository`` (``name``, ``url``, ``branch``, ``key``),
        ``scripts`` (``name`` and ``path``), ``inventory``, ``environment``
        (the body from :func:`deploy_environment`) and ``environment_prefix``.
    changes: the change log this call appends to.

    Returns:
        The ids of the inventory, of the ``inventory`` and ``scripts``
        repositories and of the environment of the project.
    """
    key_id = ensure_ssh_key(api, project_id, spec["key"], changes)
    repository_key_id = ensure_ssh_key(
        api, project_id, spec["repository"]["key"], changes
    )
    none_key_id = ensure_none_key(api, project_id, changes)
    refs = {
        "inventory": ensure_resource(
            api,
            project_id,
            "inventory",
            {
                "name": spec["inventory"],
                "project_id": project_id,
                "inventory": "",
                "ssh_key_id": key_id,
                "become_key_id": None,
                "type": "static",
            },
            matches,
            changes,
        ),
        "repositories": {
            "inventory": ensure_resource(
                api,
                project_id,
                "repositories",
                {
                    "name": spec["repository"]["name"],
                    "project_id": project_id,
                    "git_url": spec["repository"]["url"],
                    "git_branch": spec["repository"]["branch"],
                    "ssh_key_id": repository_key_id,
                },
                matches,
                changes,
            ),
            "scripts": ensure_resource(
                api,
                project_id,
                "repositories",
                {
                    "name": spec["scripts"]["name"],
                    "project_id": project_id,
                    "git_url": spec["scripts"]["path"],
                    "git_branch": "",
                    "ssh_key_id": none_key_id,
                },
                matches,
                changes,
            ),
        },
        "environment": ensure_resource(
            api,
            project_id,
            "environment",
            spec["environment"],
            lambda existing, desired: True,
            changes,
        ),
    }
    prune_keys(api, project_id, spec["key"]["prefix"], key_id, changes)
    prune_keys(
        api, project_id, spec["repository"]["key"]["prefix"], repository_key_id, changes
    )
    prune_environments(
        api, project_id, spec["environment_prefix"], refs["environment"], changes
    )
    return refs


def converge_workspaces(api, deploy, workspaces, projects, changes):
    """Args:
    api: the client.
    deploy: the ``deploy`` part of the standard input document, whose
        repository, inventory and environment the ``workspace`` template reuses.
    workspaces: ``project``, ``runner_tag``, ``key`` (as ``deploy`` holds it)
        and ``known_hosts`` the project signs in to the platform hosts with,
        ``scripts`` (``name``, ``path``,
        ``script_app``, ``deploy_script``, ``deploy_app``, ``inventory_file``),
        ``variables`` and ``secrets`` of the environment, ``store``
        (``username``, ``name``, ``email``), ``provision`` with ``project``,
        and ``export`` with ``project``, ``runner_tag`` and ``environment``,
        the plain variables of its scheduled templates.
    projects: every project the API returned.
    changes: the change log this call appends to.

    Returns:
        The post-converge findings, empty when the Workspaces, provision and
        export projects hold exactly the store's rights.
    """
    project_id = ensure_project(api, workspaces["project"], projects, changes)
    environment = deploy_environment(
        project_id,
        {
            **deploy["environment"],
            "known_hosts": workspaces["known_hosts"],
            "secrets": workspaces["secrets"],
        },
        workspaces["key"]["private_key"],
        workspaces["variables"],
    )
    refs = platform_refs(
        api,
        project_id,
        {
            "key": workspaces["key"],
            "repository": deploy["repository"],
            "scripts": workspaces["scripts"],
            "inventory": deploy["inventory"],
            "environment": environment,
            "environment_prefix": deploy["environment"]["prefix"],
        },
        changes,
    )
    store_id = ensure_user(api, workspaces["store"], changes)
    ensure_member(api, project_id, store_id, GUEST, changes)
    for entry in (*WORKSPACES_TEMPLATES, *WORKSPACES_SCHEDULED_TEMPLATES):
        body = template_body(
            project_id,
            {
                "name": entry["name"],
                **script_template(entry, workspaces["scripts"]),
                "survey": entry["survey"],
            },
            {
                "inventory": refs["inventory"],
                "repository": refs["repositories"][entry["repository"]],
                "environment": refs["environment"],
                "runner_tag": workspaces["runner_tag"],
            },
        )
        template_id = ensure_template(api, project_id, body, changes)
        if "cron" in entry:
            ensure_schedule(api, project_id, template_id, entry, changes)
        else:
            ensure_grant(api, project_id, template_id, GUEST, changes)
    platform = {}
    for kind in PLATFORM_KINDS:
        platform[kind] = ensure_project(
            api, workspaces[kind]["project"], projects, changes
        )
        ensure_member(api, platform[kind], store_id, GUEST, changes)
    converge_export_schedules(api, platform["export"], workspaces, changes)
    admins = {user["id"] for user in api.call("GET", "/users") if user.get("admin")}
    findings = grant_findings(
        api, project_id, [entry["name"] for entry in WORKSPACES_TEMPLATES], GUEST
    )
    findings.extend(
        schedule_grant_findings(api, platform["export"], EXPORT_SCHEDULED_TEMPLATES)
    )
    findings.extend(
        provision_grant_findings(api, platform["provision"], PROVISION_TEMPLATES, GUEST)
    )
    for platform_id in (project_id, *platform.values()):
        findings.extend(member_findings(api, platform_id, store_id, GUEST, admins))
    return findings


def converge_export_schedules(api, project_id, workspaces, changes):
    """Converge the scheduled templates of the export project, which carry no grant.

    Args:
        api: the client.
        project_id: the export project.
        workspaces: as for :func:`converge_workspaces`; ``scripts`` names the
            repository, inventory and environment the templates use.
        changes: the change log this call appends to.
    """
    scripts = workspaces["scripts"]
    refs = workspace_refs(
        api,
        project_id,
        {"name": scripts["name"], "url": scripts["path"], "branch": ""},
        ensure_none_key(api, project_id, changes),
        workspaces["export"]["environment"],
        workspaces["export"]["runner_tag"],
        changes,
    )
    for entry in EXPORT_SCHEDULED_TEMPLATES:
        body = template_body(
            project_id,
            {
                "name": entry["name"],
                **script_template(entry, scripts),
                "survey": entry["survey"],
            },
            refs,
        )
        template_id = ensure_template(api, project_id, body, changes)
        ensure_schedule(api, project_id, template_id, entry, changes)


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
        project_id,
        {**deploy["environment"], "secrets": {}},
        deploy["key"]["private_key"],
        {},
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
        "runner_tag": deploy["runner_tag"],
    }
    template = deploy["task_template"]
    ensure_template(
        api,
        project_id,
        template_body(
            project_id,
            {
                "name": template["name"],
                "app": template["app"],
                "playbook": template["playbook"],
                "arguments": [],
                "survey": (),
            },
            refs,
        ),
        changes,
    )
    prune_keys(api, project_id, deploy["key"]["prefix"], key_id, changes)
    prune_keys(api, project_id, repository["key"]["prefix"], repository_key_id, changes)
    prune_environments(
        api, project_id, deploy["environment"]["prefix"], refs["environment"], changes
    )


def converge(api, spec, sleep):
    """Converge the platform projects.

    Args:
        api: the client.
        spec: the standard input document.
        sleep: ``time.sleep`` or a stand-in.

    Returns:
        ``(changes, findings)``: the change log and the post-converge findings.
    """
    changes = []
    findings = []
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
        "runner_tag": spec["runner_tag"],
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
        if "workspaces" in spec:
            findings.extend(
                converge_workspaces(
                    api, spec["deploy"], spec["workspaces"], projects, changes
                )
            )
    return changes, findings


def find_project(api, hint, name):
    """Args:
    api: the client.
    hint: the project id the workspace's runner row names, None without one.
    name: the project name, ``ws-<id>``.

    Returns:
        The workspace project, found by ``hint`` when that project exists and
        else by its name; None when the workspace has no project.
    """
    if hint is not None:
        try:
            return api.call("GET", f"/project/{hint}")
        except ApiError as error:
            if not is_missing(error):
                raise
    named = [p for p in api.call("GET", "/projects") if p["name"] == name]
    if len(named) > 1:
        raise ApiError(
            f"{len(named)} projects are named {name} and no runner names one"
        )
    return named[0] if named else None


def ensure_read_key(api, project_ids, candidate, changes):
    """Args:
    api: the client.
    project_ids: the projects that clone the workspace repository.
    candidate: ``private`` and ``public`` of a fresh pair, stored only when
        a project lacks the workspace's key.
    changes: the change log this call appends to.

    Returns:
        ``(public, ids, stale)``: the public half the key's name carries, the
        key id per project, and ``(project_id, key)`` of every key the caller
        removes once no repository uses it.
    """
    held = {
        project_id: [
            key
            for key in api.call("GET", f"/project/{project_id}/keys")
            if key["type"] == "ssh" and key["name"].startswith(READ_KEY_PREFIX)
        ]
        for project_id in project_ids
    }
    names = {key["name"] for keys in held.values() for key in keys}
    if len(names) == 1 and all(len(keys) == 1 for keys in held.values()):
        name = next(iter(names))
        return (
            name[len(READ_KEY_PREFIX) :],
            {project_id: keys[0]["id"] for project_id, keys in held.items()},
            [],
        )
    public = " ".join(candidate["public"].split()[:2])
    key = {
        "name": READ_KEY_PREFIX + public,
        "login": "",
        "private_key": candidate["private"],
    }
    ids = {
        project_id: ensure_ssh_key(api, project_id, key, changes)
        for project_id in project_ids
    }
    stale = [
        (project_id, existing)
        for project_id, keys in held.items()
        for existing in keys
        if existing["name"] != key["name"]
    ]
    return public, ids, stale


def workspace_refs(api, project_id, spec, key_id, environment, runner_tag, changes):
    """Args:
    api: the client.
    project_id: the project.
    spec: ``name`` (the resource name), ``url`` and ``branch``.
    key_id: the id of the key in this project the repository is read with.
    environment: the plain variables of the environment.
    runner_tag: the tag of the runner the templates run on.
    changes: the change log this call appends to.

    Returns:
        The ids of repository, inventory and environment of the workspace in
        the project, and ``runner_tag``.
    """
    none_key_id = ensure_none_key(api, project_id, changes)
    return {
        "repository": ensure_resource(
            api,
            project_id,
            "repositories",
            {
                "name": spec["name"],
                "project_id": project_id,
                "git_url": spec["url"],
                "git_branch": spec["branch"],
                "ssh_key_id": key_id,
            },
            matches,
            changes,
        ),
        "inventory": ensure_resource(
            api,
            project_id,
            "inventory",
            {
                "name": spec["name"],
                "project_id": project_id,
                "inventory": "",
                "ssh_key_id": none_key_id,
                "become_key_id": None,
                "type": "static",
            },
            matches,
            changes,
        ),
        "environment": ensure_resource(
            api,
            project_id,
            "environment",
            {
                "name": spec["name"],
                "project_id": project_id,
                "json": EMPTY_JSON,
                "env": json.dumps(environment, sort_keys=True),
                "password": None,
                "secrets": [],
            },
            same_environment,
            changes,
        ),
        "runner_tag": runner_tag,
    }


def platform_source(api, platform_id, kind, spec, key_ids, changes):
    """Args:
    api: the client.
    platform_id: the provision or export project.
    kind: its entry of ``PLATFORM_KINDS``.
    spec: as for :func:`apply_workspace`.
    key_ids: the read key id per project of :func:`ensure_read_key`.
    changes: the change log this call appends to.

    Returns:
        ``(source, key_id)`` for :func:`workspace_refs`: for a kind of
        ``CHECKOUT_KINDS`` the workspace repository under the read key, else
        the script directory of the runner image under the project's empty
        key, as the scheduled export templates run, since that runner reaches
        no Gitea.
    """
    alias = spec["workspace"]["alias"]
    if kind in CHECKOUT_KINDS:
        return {"name": alias, **spec["repository"]}, key_ids[platform_id]
    local = {"name": alias, "url": spec["scripts"]["path"], "branch": ""}
    return local, ensure_none_key(api, platform_id, changes)


def drop_unused_read_keys(api, project_id, changes):
    """Args:
    api: the client.
    project_id: a platform project.
    changes: the change log this call appends to.

    Returns:
        None, once no workspace read key of the project is left that no
        repository of it uses.
    """
    used = {
        r["ssh_key_id"] for r in api.call("GET", f"/project/{project_id}/repositories")
    }
    for key in api.call("GET", f"/project/{project_id}/keys"):
        if (
            key["type"] == "ssh"
            and key["name"].startswith(READ_KEY_PREFIX)
            and key["id"] not in used
        ):
            delete_quietly(
                api,
                f"/project/{project_id}/keys/{key['id']}",
                f"key {key['name']} of project {project_id}",
                changes,
            )


def platform_project_id(api, name):
    """Args:
    api: the client.
    name: the name of a platform project the deploy converged.

    Returns:
        The project's id; a missing or a doubled name raises :class:`ApiError`.
    """
    named = [p["id"] for p in api.call("GET", "/projects") if p["name"] == name]
    if len(named) != 1:
        raise ApiError(f"{len(named)} projects are named {name}, expected one")
    return named[0]


def identities(api, runs, held):
    """Args:
    api: the client.
    runs: ``(project_id, template_id)`` of every template the store starts
        for the workspace.
    held: the identities already built, which this call extends.

    Returns:
        ``{template name: identity}`` as Semaphore holds it: the ids of
        project, template, repository, inventory and environment,
        the runner tag, the template's ``app``, ``playbook`` and decoded
        ``arguments``, the sorted names of its survey variables, the
        ``git_url``, ``git_branch`` and ``ssh_key_id`` of the template's
        repository, and the :func:`environment_names` of its environment.
        A name held twice raises :class:`ApiError`.
    """
    held = dict(held)
    for project_id, template_id in runs:
        template = api.call("GET", f"/project/{project_id}/templates/{template_id}")
        repository = api.call(
            "GET", f"/project/{project_id}/repositories/{template['repository_id']}"
        )
        environment = api.call(
            "GET", f"/project/{project_id}/environment/{template['environment_id']}"
        )
        if template["name"] in held:
            raise ApiError(f"the template name {template['name']} is not unique")
        if template.get("inventory_id") is None:
            raise ApiError(f"the template {template['name']} has no inventory")
        held[template["name"]] = {
            "project_id": project_id,
            "template_id": template_id,
            "repository_id": template["repository_id"],
            "inventory_id": template["inventory_id"],
            "environment_id": template["environment_id"],
            "git_url": repository["git_url"],
            "git_branch": repository["git_branch"],
            "ssh_key_id": repository["ssh_key_id"],
            "runner_tag": template.get("runner_tag"),
            "app": template["app"],
            "playbook": template["playbook"],
            "arguments": json.loads(template.get("arguments") or EMPTY_LIST_JSON),
            "survey_variables": sorted(
                survey["name"] for survey in template.get("survey_vars") or []
            ),
            "environment_variables": environment_names(environment),
        }
    return held


def environment_names(environment):
    """Args:
    environment: an environment as the Semaphore API returns it.

    Returns:
        The sorted names of its plain variables and of its ``env`` secrets,
        never a value.
    """
    names = set(json.loads(environment.get("env") or EMPTY_JSON))
    names.update(
        secret["name"]
        for secret in environment.get("secrets") or []
        if secret.get("type") == "env"
    )
    return sorted(names)


def workspaces_runs(api, name):
    """Args:
    api: the client.
    name: the name of the Workspaces project.

    Returns:
        ``(project_id, template_id)`` of each template of ``WORKSPACES_TEMPLATES``.
    """
    project_id = platform_project_id(api, name)
    templates = {
        t["name"]: t["id"] for t in api.call("GET", f"/project/{project_id}/templates")
    }
    missing = [e["name"] for e in WORKSPACES_TEMPLATES if e["name"] not in templates]
    if missing:
        raise ApiError(f"the Workspaces project lacks the templates {missing}")
    return [(project_id, templates[e["name"]]) for e in WORKSPACES_TEMPLATES]


def workspaces_identity(api, name):
    """Args:
    api: the client.
    name: the name of the Workspaces project.

    Returns:
        ``project_id`` and ``templates``, the :func:`identities` of the
        templates of ``WORKSPACES_TEMPLATES``.
    """
    runs = workspaces_runs(api, name)
    return {"project_id": runs[0][0], "templates": identities(api, runs, {})}


def store_rotation_identity(api, name):
    """Args:
    api: the client.
    name: the name of the Workspaces project.

    Returns:
        ``project_id`` and ``template_id`` of the first template of
        ``WORKSPACES_SCHEDULED_TEMPLATES``, whose task token role OpenBao binds
        to them; a missing template raises :class:`ApiError`.
    """
    project_id = platform_project_id(api, name)
    return {
        "project_id": project_id,
        "template_id": named_template_id(
            api, project_id, WORKSPACES_SCHEDULED_TEMPLATES[0]["name"]
        ),
    }


def task_entities_identity(api, name):
    """Args:
    api: the client.
    name: the name of the Workspaces project.

    Returns:
        ``project_id`` and ``template_id`` of ``TASK_ENTITIES_TEMPLATE``, whose
        task token role OpenBao binds to them; a missing template raises
        :class:`ApiError`.
    """
    project_id = platform_project_id(api, name)
    return {
        "project_id": project_id,
        "template_id": named_template_id(api, project_id, TASK_ENTITIES_TEMPLATE),
    }


def export_schedule_identity(api, name):
    """Args:
    api: the client.
    name: the name of the export project.

    Returns:
        ``project_id`` and ``templates``, the id of each template of
        ``EXPORT_SCHEDULED_TEMPLATES`` by name, whose task token roles OpenBao
        binds to them; a missing template raises :class:`ApiError`.
    """
    project_id = platform_project_id(api, name)
    return {
        "project_id": project_id,
        "templates": {
            entry["name"]: named_template_id(api, project_id, entry["name"])
            for entry in EXPORT_SCHEDULED_TEMPLATES
        },
    }


def named_template_id(api, project_id, name):
    """Args:
    api: the client.
    project_id: the project.
    name: the template name.

    Returns:
        The id of the one template of the project with that name; none or
        two raise :class:`ApiError`.
    """
    named = [
        t["id"]
        for t in api.call("GET", f"/project/{project_id}/templates")
        if t["name"] == name
    ]
    if len(named) != 1:
        raise ApiError(
            f"{len(named)} templates of project {project_id} are named {name}"
        )
    return named[0]


def ensure_probe(api, project_id, name, scripts, refs, changes):
    """Args:
    api: the client.
    project_id: the workspace project or a platform project.
    name: ``probe`` in the workspace project, ``probe ws-<id>`` in a
        platform project.
    scripts: as in :func:`script_template`.
    refs: the project's refs, so the probe runs as that project's tasks do.
    changes: the change log this call appends to.

    Returns:
        The id of the locked probe template, which carries no grant and stays
        out of the identity ``apply`` prints.
    """
    return ensure_template(
        api,
        project_id,
        template_body(
            project_id,
            {
                "name": name,
                **script_template(PROBE_TEMPLATE, scripts),
                "survey": PROBE_TEMPLATE["survey"],
            },
            refs,
        ),
        changes,
    )


def apply_workspace(api, spec, changes, sleep):
    """Args:
    api: the client.
    spec: ``workspace`` (``id``, ``alias``, ``project_hint``), ``store``
        (``username``), ``repository`` (``url``, ``branch``), ``read_key``
        (the candidate of :func:`ensure_read_key`), ``scripts`` (as in
        :func:`converge_workspaces`), ``environment`` (the plain variables of
        the workspace project), ``workspaces`` (``project``), ``provision``
        (``project``, ``runner_tag``, ``environment``), ``export``
        (``project``, ``runner_tag``, ``environment``) and ``probe``, true
        only in a test runtime, where every project of the workspace gets
        the locked probe template.
    changes: the change log this call appends to.
    sleep: ``time.sleep`` or a stand-in, for the stop of a pruned template's
        tasks.

    Returns:
        ``result``, the object the operation prints as its last line, and
        ``semaphore``, the ids the roles that run after it read.
    """
    workspace = spec["workspace"]
    alias = workspace["alias"]
    project = find_project(api, workspace["project_hint"], alias)
    if project is None:
        project = api.call("POST", "/projects", {"name": alias})
        changes.append(f"project {alias} created")
    elif project["name"] != alias:
        api.call("PUT", f"/project/{project['id']}", {**project, "name": alias})
        changes.append(f"project {project['id']} renamed to {alias}")
    project_id = project["id"]
    store = find_user(api, spec["store"]["username"])
    if store is None:
        raise ApiError(f"the store account {spec['store']['username']} is missing")
    ensure_member(api, project_id, store["id"], MANAGER, changes)
    platform = {
        kind: platform_project_id(api, spec[kind]["project"]) for kind in PLATFORM_KINDS
    }
    public, key_ids, stale = ensure_read_key(
        api,
        [project_id, *(platform[kind] for kind in CHECKOUT_KINDS)],
        spec["read_key"],
        changes,
    )
    refs = workspace_refs(
        api,
        project_id,
        {"name": WORKSPACE_RESOURCE, **spec["repository"]},
        key_ids[project_id],
        spec["environment"],
        alias,
        changes,
    )
    runs = [
        (
            project_id,
            ensure_template(
                api,
                project_id,
                template_body(
                    project_id,
                    {
                        "name": entry["name"],
                        **script_template(entry, spec["scripts"]),
                        "survey": entry["survey"],
                    },
                    refs,
                ),
                changes,
            ),
        )
        for entry in WORKSPACE_TEMPLATES
    ]
    for (_, template_id), entry in zip(runs, WORKSPACE_TEMPLATES, strict=True):
        if "cron" in entry:
            ensure_schedule(api, project_id, template_id, entry, changes)
    if spec["probe"] is True:
        ensure_probe(
            api, project_id, PROBE_TEMPLATE["name"], spec["scripts"], refs, changes
        )
    ids = {}
    for kind, platform_id in platform.items():
        source, key_id = platform_source(api, platform_id, kind, spec, key_ids, changes)
        project_refs = workspace_refs(
            api,
            platform_id,
            source,
            key_id,
            spec[kind]["environment"],
            spec[kind]["runner_tag"],
            changes,
        )
        if kind not in CHECKOUT_KINDS:
            drop_unused_read_keys(api, platform_id, changes)
        for entry in PLATFORM_TEMPLATES[kind]:
            template_id = ensure_template(
                api,
                platform_id,
                template_body(
                    platform_id,
                    {
                        "name": f"{entry['name']} {alias}",
                        **script_template(entry, spec["scripts"]),
                        "survey": entry["survey"],
                    },
                    project_refs,
                ),
                changes,
            )
            ensure_grant(api, platform_id, template_id, GUEST, changes)
            ids.setdefault(kind, {})[entry["name"]] = template_id
            runs.append((platform_id, template_id))
        kept = {f"{entry['name']} {alias}" for entry in PLATFORM_TEMPLATES[kind]}
        if spec["probe"] is True:
            kept.add(f"{PROBE_TEMPLATE['name']} {alias}")
            ensure_probe(
                api,
                platform_id,
                f"{PROBE_TEMPLATE['name']} {alias}",
                spec["scripts"],
                project_refs,
                changes,
            )
        prune_workspace_templates(api, platform_id, alias, kept, changes, sleep)
    for platform_id, key in stale:
        delete_quietly(
            api,
            f"/project/{platform_id}/keys/{key['id']}",
            f"key {key['name']} of project {platform_id}",
            changes,
        )
    workspaces = workspaces_identity(api, spec["workspaces"]["project"])
    return {
        "result": {
            "workspace": workspace["id"],
            "alias": alias,
            "read_key": public,
            "project_id": project_id,
            "templates": identities(api, runs, workspaces["templates"]),
        },
        "semaphore": {
            "project_id": project_id,
            "workspaces_project_id": workspaces["project_id"],
            "members_template_id": workspaces["templates"][MEMBERS_TEMPLATE][
                "template_id"
            ],
            "provision_project_id": platform["provision"],
            "provider_templates": {
                provider: {
                    action: ids["provision"][f"{action}-{provider}"]
                    for action in ORDER_ACTIONS
                }
                for provider in PROVISION_PROVIDERS
            },
            "unlock_template_id": ids["provision"]["unlock"],
            "dns_template_id": ids["provision"]["dns"],
            "zone_template_id": ids["provision"]["zone"],
            "export_project_id": platform["export"],
            "export_template_id": ids["export"]["export"],
        },
    }


def prune_workspace_templates(api, project_id, alias, kept, changes, sleep):
    """Remove the templates of a workspace that an earlier template set left,
    once :func:`stop_tasks` stopped their unfinished tasks.

    Args:
        api: the client.
        project_id: a platform project.
        alias: ``ws-<id>``, the end of each template name of the workspace there.
        kept: the names of the workspace's templates there that stay.
        changes: the change log this call appends to.
        sleep: ``time.sleep`` or a stand-in.
    """
    path = f"/project/{project_id}/templates"
    pruned = [
        template
        for template in api.call("GET", path)
        if template["name"].endswith(f" {alias}") and template["name"] not in kept
    ]
    stop_tasks(api, [(project_id, t["id"]) for t in pruned], changes, sleep)
    for template in pruned:
        api.call("DELETE", f"{path}/{template['id']}")
        changes.append(f"template {template['name']} of project {project_id} removed")


def delete_quietly(api, path, what, changes):
    """Args:
    api: the client.
    path: the object's path; an object already gone counts as removed.
    what: how the change log names the object.
    changes: the change log this call appends to.
    """
    try:
        api.call("DELETE", path)
    except ApiError as error:
        if not is_missing(error):
            raise
        return
    changes.append(f"{what} removed")


def workspace_templates(api, platform_ids, suffix, project):
    """Args:
    api: the client.
    platform_ids: the ids of the provision and export projects.
    suffix: `` ws-<id>``, the end of each template name of the workspace there.
    project: the project ``ws-<id>``, None when it is gone.

    Returns:
        ``(project_id, template_id)`` of every template of ``project`` and of
        every template of the platform projects whose name ends in ``suffix``.
    """
    held = [
        (platform_id, template["id"])
        for platform_id in platform_ids
        for template in api.call("GET", f"/project/{platform_id}/templates")
        if template["name"].endswith(suffix)
    ]
    if project is not None:
        held.extend(
            (project["id"], template["id"])
            for template in api.call("GET", f"/project/{project['id']}/templates")
        )
    return held


def wait_until_finished(api, tasks, sleep):
    """Args:
    api: the client.
    tasks: ``(project_id, task_id)`` of every task a stop was sent to.
    sleep: ``time.sleep`` or a stand-in.

    Returns:
        Once every task reports a status of ``FINISHED_STATUSES``; a task
        still unfinished ``STOP_TIMEOUT`` seconds later raises
        :class:`ApiError` naming its id.
    """
    pending = list(tasks)
    for attempt in range(STOP_TIMEOUT // STOP_DELAY + 1):
        if attempt:
            sleep(STOP_DELAY)
        pending = [
            (project_id, task_id)
            for project_id, task_id in pending
            if api.call("GET", f"/project/{project_id}/tasks/{task_id}").get("status")
            not in FINISHED_STATUSES
        ]
        if not pending:
            return
    ids = ", ".join(str(task_id) for _, task_id in pending)
    raise ApiError(
        f"the tasks {ids} are still unfinished {STOP_TIMEOUT} seconds after their "
        "stop, so the templates they run are kept"
    )


def stop_tasks(api, templates, changes, sleep):
    """Args:
    api: the client.
    templates: the pairs of :func:`workspace_templates`.
    changes: the change log this call appends to.
    sleep: ``time.sleep`` or a stand-in.

    Returns:
        How many tasks of ``templates`` it found unfinished and stopped,
        waiting with :func:`wait_until_finished`; 0 when none was unfinished.
    """
    active = [
        (project_id, task["id"])
        for project_id, template_id in templates
        for task in api.call(
            "GET", f"/project/{project_id}/templates/{template_id}/tasks"
        )
        or []
        if task.get("status") not in FINISHED_STATUSES
    ]
    for project_id, task_id in active:
        api.call(
            "POST", f"/project/{project_id}/tasks/{task_id}/stop", {"force": False}
        )
        changes.append(f"task {task_id} of project {project_id} stopped")
    wait_until_finished(api, active, sleep)
    return len(active)


def workspace_scope(api, spec):
    """Args:
    api: the client.
    spec: ``workspace`` (``alias``, ``project_hint``) and the ``project`` of
        ``provision`` and ``export``.

    Returns:
        ``(platform_ids, project)``: the ids of the provision and export
        projects and the project ``ws-<id>``, None when it is gone.
    """
    names = {spec[kind]["project"] for kind in PLATFORM_KINDS}
    platform_ids = [p["id"] for p in api.call("GET", "/projects") if p["name"] in names]
    workspace = spec["workspace"]
    return platform_ids, find_project(
        api, workspace["project_hint"], workspace["alias"]
    )


def stop_workspace(api, spec, changes, sleep):
    """Args:
    api: the client.
    spec: as for :func:`workspace_scope`.
    changes: the change log this call appends to.
    sleep: ``time.sleep`` or a stand-in.

    Returns:
        What :func:`stop_tasks` stopped of the workspace's templates.
    """
    platform_ids, project = workspace_scope(api, spec)
    suffix = f" {spec['workspace']['alias']}"
    return stop_tasks(
        api, workspace_templates(api, platform_ids, suffix, project), changes, sleep
    )


def destroy_workspace(api, spec, changes, sleep):
    """Args:
    api: the client.
    spec: the workspace operation document, as for :func:`apply_workspace`.
    changes: the change log this call appends to.
    sleep: ``time.sleep`` or a stand-in.

    Returns:
        What :func:`stop_workspace` stopped before the first erase.
    """
    alias = spec["workspace"]["alias"]
    suffix = f" {alias}"
    stopped = stop_workspace(api, spec, changes, sleep)
    platform_ids, project = workspace_scope(api, spec)
    for platform_id in platform_ids:
        for template in api.call("GET", f"/project/{platform_id}/templates"):
            if template["name"].endswith(suffix):
                delete_quietly(
                    api,
                    f"/project/{platform_id}/templates/{template['id']}",
                    f"template {template['name']}",
                    changes,
                )
        for collection in ("environment", "inventory", "repositories"):
            for item in api.call("GET", f"/project/{platform_id}/{collection}"):
                if item["name"] == alias:
                    delete_quietly(
                        api,
                        f"/project/{platform_id}/{collection}/{item['id']}",
                        f"{collection} {alias} of project {platform_id}",
                        changes,
                    )
        drop_unused_read_keys(api, platform_id, changes)
    if project is not None:
        delete_quietly(api, f"/project/{project['id']}", f"project {alias}", changes)
    return stopped


def run_workspace(api, spec, sleep):
    """Args:
    api: the client.
    spec: the workspace operation document.
    sleep: ``time.sleep`` or a stand-in.

    Returns:
        ``(changes, applied)``: the change log and, for ``apply``, what
        :func:`apply_workspace` returned; for ``stop`` and ``destroy``,
        ``result`` with ``workspace`` and ``stopped_tasks``, the count of
        :func:`stop_workspace` or :func:`destroy_workspace`.
    """
    changes = []
    wait_until_ready(api, READY_ATTEMPTS, READY_DELAY, sleep)
    operations = {"stop": stop_workspace, "destroy": destroy_workspace}
    if spec["workspace"]["action"] in operations:
        operation = operations[spec["workspace"]["action"]]
        stopped = operation(api, spec, changes, sleep)
        return changes, {
            "result": {"workspace": spec["workspace"]["id"], "stopped_tasks": stopped}
        }
    applied = apply_workspace(api, spec, changes, sleep)
    return changes, applied


def main(argv, stdin=sys.stdin, opener=urllib.request.urlopen, sleep=time.sleep):
    """Run the convergence and return the exit code.

    Args:
        argv: empty, ``[IDENTITY_COMMAND]`` to print only
            :func:`workspaces_identity` or ``[ROTATION_COMMAND]`` to print only
            :func:`store_rotation_identity` or ``[TASK_ENTITIES_COMMAND]`` to
            print only :func:`task_entities_identity`, each of
            ``workspaces.project``, or ``[EXPORT_SCHEDULE_COMMAND]`` to print
            only :func:`export_schedule_identity` of
            ``workspaces.export.project``, each as JSON.
        stdin: the stream carrying the input document.
        opener: ``urllib.request.urlopen`` or a stand-in.
        sleep: ``time.sleep`` or a stand-in.
    """
    readers = {
        IDENTITY_COMMAND: lambda api, spec: workspaces_identity(api, spec["project"]),
        ROTATION_COMMAND: lambda api, spec: store_rotation_identity(
            api, spec["project"]
        ),
        EXPORT_SCHEDULE_COMMAND: lambda api, spec: export_schedule_identity(
            api, spec["export"]["project"]
        ),
        TASK_ENTITIES_COMMAND: lambda api, spec: task_entities_identity(
            api, spec["project"]
        ),
    }
    if argv != [] and (len(argv) != 1 or argv[0] not in readers):
        print(
            f"semaphore project: expects no argument or {IDENTITY_COMMAND} or "
            f"{ROTATION_COMMAND} or {EXPORT_SCHEDULE_COMMAND} or "
            f"{TASK_ENTITIES_COMMAND}",
            file=sys.stderr,
        )
        return 2
    spec = json.load(stdin)
    api = Api(spec["url"], spec["token"], opener)
    findings = []
    applied = None
    try:
        if argv:
            wait_until_ready(api, READY_ATTEMPTS, READY_DELAY, sleep)
            identity = readers[argv[0]](api, spec["workspaces"])
            print(json.dumps(identity, sort_keys=True))
            return 0
        if "workspace" in spec:
            changes, applied = run_workspace(api, spec, sleep)
        else:
            changes, findings = converge(api, spec, sleep)
    except ApiError as error:
        print(f"semaphore project: {error}", file=sys.stderr)
        return 1
    for change in changes:
        print(f"CHANGED {change}")
    if not changes:
        print("UNCHANGED")
    if applied is not None:
        print("RESULT " + json.dumps(applied, sort_keys=True))
    for finding in findings:
        print(f"FINDING {finding}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
