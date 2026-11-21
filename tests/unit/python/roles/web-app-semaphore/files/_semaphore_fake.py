from __future__ import annotations

import copy
import json
import posixpath
import re
from importlib.util import module_from_spec, spec_from_file_location

from utils.cache.files import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
PYTHON_DIR = ROLE / "files" / "python"
SCRIPT = PYTHON_DIR / "project.py"
SCRIPTS_DIR = ROLE / "files" / "shell" / "repository"
PROJECT = re.compile(r"^/project/(\d+)$")
COLLECTION = re.compile(r"^/project/(\d+)/([a-z]+)(?:/(\d+))?$")
PERMS = re.compile(r"^/project/(\d+)/templates/(\d+)/perms(?:/(\d+))?$")
TEMPLATE_TASKS = re.compile(r"^/project/(\d+)/templates/(\d+)/tasks$")
TASK_STOP = re.compile(r"^/project/(\d+)/tasks/(\d+)/stop$")
FINISHED = ("success", "error", "stopped")
STORE = {"username": "store", "name": "Store", "email": "store@semaphore.invalid"}
WORKSPACE_ID = "0b6f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4"
ALIAS = f"ws-{WORKSPACE_ID}"
SCRIPTS = {
    "name": "scripts",
    "path": "/opt/app-control",
    "script_app": "infinito-script",
    "deploy_script": "deploy.sh",
    "deploy_app": "infinito",
    "inventory_file": "devices.yml",
}
CHANGELOG = "# Changelog\n\n## [17.0.0] - 2026-11-08\n\n## [16.2.0] - 2026-10-01\n"
SUSPENSION_REFUSALS = (
    (None, "missing"),
    ("", "missing"),
    ("yes", "malformed"),
    ("True", "malformed"),
    ("true\n", "malformed"),
)


def playbook_refusal(playbook):
    """Args:
    playbook: the playbook of a template body.

    Returns:
        Why Semaphore refuses it on a template write (``ValidatePlaybookPath``
        of ``db/playbook_path.go``, v2.20.24), None when it takes it.
    """
    path = playbook.replace("\\", "/")
    if path.startswith("/") or path[1:2] == ":":
        return "template playbook must be a relative path inside the repository"
    cleaned = posixpath.normpath(path)
    if cleaned.split("/", 1)[0] == "..":
        return "template playbook must not point outside the repository"
    return None


def load_project():
    """Returns:
    The converger module ``files/python/project.py``.
    """
    spec = spec_from_file_location("semaphore_project", str(SCRIPT))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_workspace():
    """Returns:
    The module ``files/python/workspace.py``.
    """
    spec = spec_from_file_location(
        "semaphore_workspace", str(PYTHON_DIR / "workspace.py")
    )
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeSemaphore:
    """Args:
    error: the ``ApiError`` class of the converger, raised with HTTP 404 for
        a missing object.
    """

    def __init__(self, error):
        self.error = error
        self.projects = []
        self.objects = {}
        self.members = {}
        self.perms = {}
        self.users = [{"id": 1, "username": "breakglass-admin", "admin": True}]
        self.next_id = 100
        self.writes = []
        self.bodies = []
        self.tasks = []
        self.stuck = set()
        self.at_first_erase = None

    def _new_id(self):
        self.next_id += 1
        return self.next_id

    def _missing(self, method, path):
        raise self.error(f"{method} {path}: HTTP 404 not found")

    def _store(self, project_id, collection, body):
        stored = {**copy.deepcopy(body), "id": self._new_id()}
        if collection == "keys":
            stored.pop("ssh", None)
        if collection == "environment":
            stored["secrets"] = [
                {"id": self._new_id(), "type": s["type"], "name": s["name"]}
                for s in stored.get("secrets", [])
            ]
        self.objects.setdefault((project_id, collection), []).append(stored)
        return stored

    def _project(self, project_id):
        return next((p for p in self.projects if p["id"] == project_id), None)

    def add_project(self, name):
        project = {"id": self._new_id(), "name": name}
        self.projects.append(project)
        self._store(project["id"], "keys", {"name": "None", "type": "none"})
        self.members[project["id"]] = {1: "owner"}
        return project

    def add_task(self, project_id, template_id, status):
        """Args:
        project_id: the project of the task.
        template_id: the template it runs.
        status: its Semaphore status, e.g. ``waiting`` or ``running``.

        Returns:
            The stored task.
        """
        task = {
            "id": self._new_id(),
            "project_id": project_id,
            "template_id": template_id,
            "status": status,
        }
        self.tasks.append(task)
        return task

    def _task(self, method, path, project_id, task_id):
        task = next(
            (
                t
                for t in self.tasks
                if t["id"] == task_id and t["project_id"] == project_id
            ),
            None,
        )
        if task is None:
            self._missing(method, path)
        return task

    def _template_tasks(self, method, path, match):
        project_id, template_id = int(match.group(1)), int(match.group(2))
        templates = self.objects.get((project_id, "templates"), [])
        if not any(t["id"] == template_id for t in templates):
            self._missing(method, path)
        return [
            copy.deepcopy(t)
            for t in self.tasks
            if t["project_id"] == project_id and t["template_id"] == template_id
        ]

    def _stop_task(self, method, path, match):
        task = self._task(method, path, int(match.group(1)), int(match.group(2)))
        if task["status"] not in FINISHED:
            task["status"] = "stopping"

    def _read_task(self, method, path, project_id, task_id):
        task = self._task(method, path, project_id, task_id)
        if task["status"] == "stopping" and task_id not in self.stuck:
            task["status"] = "stopped"
        return copy.deepcopy(task)

    def call(self, method, path, body=None):
        if method != "GET":
            self.writes.append((method, path))
            self.bodies.append((method, path, copy.deepcopy(body)))
        if method == "DELETE" and self.at_first_erase is None:
            self.at_first_erase = {t["id"]: t["status"] for t in self.tasks}
        if path == "/projects":
            if method == "GET":
                return copy.deepcopy(self.projects)
            return copy.deepcopy(self.add_project(body["name"]))
        if path == "/users":
            if method == "GET":
                return copy.deepcopy(self.users)
            user = {**{k: v for k, v in body.items() if k != "password"}}
            user["id"] = self._new_id()
            self.users.append(user)
            return copy.deepcopy(user)
        match = PROJECT.match(path)
        if match:
            return self._project_call(method, path, int(match.group(1)), body)
        match = PERMS.match(path)
        if match:
            return self._perms_call(method, path, match, body)
        match = TEMPLATE_TASKS.match(path)
        if match:
            return self._template_tasks(method, path, match)
        match = TASK_STOP.match(path)
        if match:
            return self._stop_task(method, path, match)
        match = COLLECTION.match(path)
        project_id = int(match.group(1))
        if self._project(project_id) is None:
            self._missing(method, path)
        collection, object_id = match.group(2), match.group(3)
        if collection == "users":
            return self._members_call(method, project_id, object_id, body)
        if collection == "tasks" and object_id is not None:
            return self._read_task(method, path, project_id, int(object_id))
        if collection == "tasks":
            return {"id": self._new_id(), **copy.deepcopy(body)}
        if collection == "templates" and method in ("POST", "PUT"):
            refusal = playbook_refusal(body.get("playbook") or "")
            if refusal:
                raise self.error(f"{method} {path}: HTTP 400 {refusal}")
        items = self.objects.setdefault((project_id, collection), [])
        if method == "GET" and object_id is None:
            return copy.deepcopy(items)
        if method == "POST":
            return self._store(project_id, collection, body)
        index = next(
            (i for i, item in enumerate(items) if item["id"] == int(object_id)), None
        )
        if index is None:
            self._missing(method, path)
        if method == "GET":
            return copy.deepcopy(items[index])
        if method == "PUT":
            items[index] = copy.deepcopy(body)
            return None
        del items[index]
        if collection == "templates":
            self.tasks[:] = [
                t
                for t in self.tasks
                if (t["project_id"], t["template_id"]) != (project_id, int(object_id))
            ]
            self.perms.pop((project_id, int(object_id)), None)
            schedules = self.objects.get((project_id, "schedules"), [])
            schedules[:] = [s for s in schedules if s["template_id"] != int(object_id)]
        return None

    def _project_call(self, method, path, project_id, body):
        project = self._project(project_id)
        if project is None:
            self._missing(method, path)
        if method == "GET":
            return copy.deepcopy(project)
        if method == "PUT":
            project["name"] = body["name"]
            return None
        self.projects.remove(project)
        self.tasks[:] = [t for t in self.tasks if t["project_id"] != project_id]
        for key in [k for k in self.objects if k[0] == project_id]:
            del self.objects[key]
        self.members.pop(project_id, None)
        return None

    def _perms_call(self, method, path, match, body):
        project_id, template_id = int(match.group(1)), int(match.group(2))
        grants = self.perms.setdefault((project_id, template_id), [])
        if method == "GET":
            return copy.deepcopy(grants)
        if method == "POST":
            grant = {**copy.deepcopy(body), "id": self._new_id()}
            grants.append(grant)
            return grant
        grant_id = int(match.group(3))
        if not any(g["id"] == grant_id for g in grants):
            self._missing(method, path)
        grants[:] = [g for g in grants if g["id"] != grant_id]
        return None

    def _members_call(self, method, project_id, user_id, body):
        members = self.members.setdefault(project_id, {})
        if method == "GET":
            return [
                {"id": uid, "username": self.username(uid), "role": role}
                for uid, role in sorted(members.items())
            ]
        if method == "POST":
            members[body["user_id"]] = body["role"]
            return None
        if method == "PUT":
            members[int(user_id)] = body["role"]
            return None
        members.pop(int(user_id), None)
        return None

    def username(self, user_id):
        return next(u["username"] for u in self.users if u["id"] == user_id)

    def names(self, project_id, collection):
        return sorted(item["name"] for item in self.objects[(project_id, collection)])

    def project_id(self, name):
        return next(p["id"] for p in self.projects if p["name"] == name)

    def templates(self, project_id):
        return {t["name"]: t for t in self.objects.get((project_id, "templates"), [])}

    def schedules(self, project_id):
        return list(self.objects.get((project_id, "schedules"), []))

    def written(self, collection):
        return [
            body
            for method, path, body in self.bodies
            if method in ("POST", "PUT")
            and COLLECTION.match(path)
            and COLLECTION.match(path).group(2) == collection
        ]


def app_control_spec(applications, key_name="app-control 0123456789ab"):
    """Args:
    applications: the application ids under app control.
    key_name: the name of the app-control key.

    Returns:
        The platform document of the app-control project alone.
    """
    return {
        "url": "http://127.0.0.1:3000/api",
        "token": "deploytoken",
        "project": "Infinito.Nexus",
        "runner_tag": "app-control",
        "key": {
            "name": key_name,
            "prefix": "app-control ",
            "login": "app-control",
            "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nkey\n-----END OPENSSH PRIVATE KEY-----",
        },
        "hosts": ["host.docker.internal"],
        "known_hosts": ["host.docker.internal ssh-ed25519 AAAAhostkey"],
        "inventory": "app-control",
        "repository": {"name": "app-control", "path": "/opt/app-control"},
        "environment": "app-control",
        "playbook": "app-control.sh",
        "applications": applications,
    }


def deploy_spec():
    """Returns:
    The ``deploy`` part of the platform document.
    """
    return {
        "project": "Infinito.Nexus Deploy",
        "runner_tag": "deploy",
        "key": {
            "name": "deploy 111111111111",
            "prefix": "deploy ",
            "login": "root",
            "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\ndeploy\n-----END OPENSSH PRIVATE KEY-----",
        },
        "repository": {
            "name": "inventory",
            "url": "ssh://git@git.example.org:2201/administrator/target-inventory.git",
            "branch": "main",
            "key": {
                "name": "inventory 222222222222",
                "prefix": "inventory ",
                "login": "",
                "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nrepository\n-----END OPENSSH PRIVATE KEY-----",
            },
        },
        "inventory": "deploy",
        "environment": {
            "prefix": "deploy ",
            "login": "root",
            "known_hosts": ["target ssh-ed25519 AAAAtargetkey"],
            "vault_password": "vaultpassword",
        },
        "task_template": {
            "name": "deploy",
            "app": "infinito",
            "playbook": "devices.yml",
        },
    }


def workspaces_spec():
    """Returns:
    The ``workspaces`` part of the platform document.
    """
    deploy = deploy_spec()
    return {
        "project": "Infinito.Nexus Workspaces",
        "runner_tag": "workspaces",
        "key": deploy["key"],
        "known_hosts": deploy["environment"]["known_hosts"],
        "scripts": dict(SCRIPTS),
        "variables": {"WORKSPACE_PRIVATE_TARGETS": "[]"},
        "secrets": {"MEMBERS_CLIENT_SECRET": "membersecret"},
        "store": dict(STORE),
        "provision": {"project": "Infinito.Nexus Provision"},
        "export": {
            "project": "Infinito.Nexus Export",
            "runner_tag": "export",
            "environment": {
                "BAO_ADDR": "https://openbao.example.org",
                "EXPORT_S3_ENDPOINT": "https://s3.example.org",
            },
        },
    }


def platform_spec():
    """Returns:
    The full platform document with the deploy and the Workspaces project.
    """
    return {
        **app_control_spec(["web-app-wiki"]),
        "deploy": deploy_spec(),
        "workspaces": workspaces_spec(),
    }


def workspace_spec(
    action="apply", hint=None, public="ssh-ed25519 AAAAread1", probe=False
):
    """Args:
    action: ``apply`` or ``destroy``.
    hint: the project id of the workspace's runner row.
    public: the public half of the candidate read key.
    probe: whether the stack is a test runtime whose workspaces get the probe.

    Returns:
        The workspace operation document.
    """
    return {
        "url": "http://127.0.0.1:3000/api",
        "token": "admintoken",
        "probe": probe,
        "workspace": {
            "id": WORKSPACE_ID,
            "alias": ALIAS,
            "action": action,
            "project_hint": hint,
        },
        "store": {"username": STORE["username"]},
        "repository": {
            "url": f"ssh://git@git.example.org:2201/workspaces/{ALIAS}.git",
            "branch": "main",
        },
        "read_key": {
            "private": "-----BEGIN OPENSSH PRIVATE KEY-----\nread\n-----END OPENSSH PRIVATE KEY-----",
            "public": public,
        },
        "scripts": dict(SCRIPTS),
        "environment": {
            "WORKSPACE": WORKSPACE_ID,
            "WORKSPACE_DNS_ZONE": "ws.example.org",
            "WORKSPACE_TARGETS": "203.0.113.10:22",
        },
        "provision": {
            "project": "Infinito.Nexus Provision",
            "runner_tag": "provision",
            "environment": {
                "WORKSPACE": ALIAS,
                "WORKSPACE_DNS_ZONE": "ws.example.org",
                "WORKSPACE_DNS_ZONE_ID": "",
                "WORKSPACE_TARGETS": "203.0.113.10:22",
            },
        },
        "export": {
            "project": "Infinito.Nexus Export",
            "runner_tag": "export",
            "environment": {},
        },
        "workspaces": {"project": "Infinito.Nexus Workspaces"},
    }


def env_secret_names(body):
    """Args:
    body: an environment body.

    Returns:
        ``(type, name)`` of every secret the body carries.
    """
    return [(s["type"], s["name"]) for s in body.get("secrets") or []]


def decoded(body):
    """Args:
    body: an environment body.

    Returns:
        Its plain variables.
    """
    return json.loads(body.get("env") or "{}")
