from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles/web-svc-access-request"
TASKS = ROLE / "tasks"
STAGE = TASKS / "utils/stack/stage.yml"
CORE = TASKS / "00_core.yml"
VARS = ROLE / ROLE_FILE_VARS_MAIN
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VOLUMES = ROLE / ROLE_FILE_META_VOLUMES
TLS_VARS = PROJECT_ROOT / "group_vars/all/02_tls.yml"
CA_MAIN = PROJECT_ROOT / "roles/sys-ca-selfsigned" / ROLE_FILE_TASKS_MAIN
CA_CORE = PROJECT_ROOT / "roles/sys-ca-selfsigned/tasks/00_core.yml"
SWARM_NODE_CORE = PROJECT_ROOT / "roles/svc-swarm-node/tasks/00_core.yml"
COMPOSE_MAIN = PROJECT_ROOT / "roles/sys-svc-compose" / ROLE_FILE_TASKS_MAIN
NFS_PREP = PROJECT_ROOT / "roles/sys-svc-compose/tasks/utils/nfs_prep.yml"
RENDERER = "roles/sys-svc-compose/tasks/utils/render_replicated_templates.yml"
STACK_HOST_ONLY = ("stack_host_template", "stack_host_copy")
CONFIG_HOST = "ACCESS_REQUEST_CONFIG_HOST"
CA_HOST = "CA_TRUST.cert_host"
CHANGED = "access_request_config_changed"
SELF_SIGNED = "(TLS_MODE | lower) == 'self_signed'"
MOUNT_SOURCE = re.compile(r"([A-Z][A-Z0-9_]*(?:\.[a-z_]+)?)\s*~\s*':'")
NOT_STACK_HOST = re.compile(r"^\s*not\s*\(\s*IS_STACK_HOST\s*\|\s*bool\s*\)\s*$")
NODE_LOCAL = ("run_once", "delegate_to")
INCLUDES = ("ansible.builtin.include_tasks", "include_tasks")
ROLE_INCLUDES = ("ansible.builtin.include_role", "include_role")

Scoped = tuple[dict, list[dict]]


def _scoped(path: Path) -> list[Scoped]:
    """Args:
        path: the task file; a missing one has no tasks.

    Returns:
        Every task of the file, blocks flattened in, each with the blocks
        that enclose it, outermost first.
    """
    if not path.is_file():
        return []
    out: list[Scoped] = []
    queue: list[Scoped] = [
        (task, []) for task in load_yaml_str(read_text(str(path))) or []
    ]
    while queue:
        task, parents = queue.pop(0)
        if not isinstance(task, dict):
            continue
        out.append((task, parents))
        for nested in ("block", "rescue", "always"):
            queue.extend((child, [*parents, task]) for child in task.get(nested) or [])
    return out


def _tasks(path: Path) -> list[dict]:
    return [task for task, _ in _scoped(path)]


def _yaml(path: Path) -> dict:
    return load_yaml_str(read_text(str(path))) or {}


def _spec(task: dict, keys: tuple[str, ...]) -> dict:
    for key in keys:
        value = task.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return {"file": value}
    return {}


def _whens(task: dict, parents: list[dict]) -> list[str]:
    """Args:
        task: one task.
        parents: the blocks enclosing it.

    Returns:
        Every condition the task runs under, its own and inherited ones.
    """
    out: list[str] = []
    for step in [*parents, task]:
        when = step.get("when")
        if isinstance(when, list):
            out.extend(str(item) for item in when)
        elif when is not None:
            out.append(str(when))
    return out


def _on_every_host(task: dict, parents: list[dict]) -> bool:
    """Args:
        task: one task.
        parents: the blocks enclosing it.

    Returns:
        Whether neither the task, an enclosing block nor an include's apply
        narrows it to one host through run_once or delegate_to.
    """
    for step in [*parents, task]:
        scopes = [step, _spec(step, INCLUDES).get("apply") or {}]
        scopes.append(_spec(step, ROLE_INCLUDES).get("apply") or {})
        if any(key in scope for scope in scopes for key in NODE_LOCAL):
            return False
    return True


def _writers(path: Path, module: str, field: str, var: str) -> list[Scoped]:
    return [
        (task, parents)
        for task, parents in _scoped(path)
        if var in str((task.get(module) or {}).get(field, ""))
    ]


def _per_host_writer(path: Path, module: str, field: str, var: str) -> bool:
    found = _writers(path, module, field, var)
    return len(found) == 1 and _on_every_host(*found[0])


def _stage_config_entries() -> list[dict]:
    return [
        entry
        for task in _tasks(STAGE)
        if RENDERER in _spec(task, INCLUDES).get("file", "")
        for entry in (task.get("vars") or {}).get("role_templates") or []
        if CONFIG_HOST in str(entry["dest"])
    ]


def _role_task_files() -> list[Path]:
    prefix = str(TASKS) + "/"
    return [
        Path(path)
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(prefix)
    ]


def _ca_reaches_every_swarm_node() -> bool:
    includes = [
        (task, parents)
        for task, parents in _scoped(SWARM_NODE_CORE)
        if _spec(task, ROLE_INCLUDES).get("name") == "sys-ca-selfsigned"
    ]
    core_includes = [
        (task, parents)
        for task, parents in _scoped(CA_MAIN)
        if _spec(task, INCLUDES).get("file") == "00_core.yml"
    ]
    return (
        len(includes) == 1
        and "IS_SWARM_MODE" in _whens(*includes[0])
        and SELF_SIGNED in _whens(*includes[0])
        and _on_every_host(*includes[0])
        and len(core_includes) == 1
        and _on_every_host(*core_includes[0])
    )


class TestBindSourcesOnEveryNode(unittest.TestCase):
    def test_the_stage_replicates_config_json_without_a_compose_notify(self) -> None:
        self.assertEqual(
            [(entry["src"], entry.get("notify")) for entry in _stage_config_entries()],
            [("config.json.j2", [])],
            "swarm schedules access-request on any node, so config.json must "
            "exist on all of them before the backend deploys the stack; the "
            "stage runs before compose.yml exists, so it notifies nothing",
        )

    def test_no_task_renders_config_json_on_the_stack_host_only(self) -> None:
        files = _role_task_files()
        self.assertTrue({CORE, STAGE} <= set(files), files)
        offenders = [
            f"{path}: {module}"
            for path in files
            for task in _tasks(path)
            for module in STACK_HOST_ONLY
            if CONFIG_HOST in str((task.get(module) or {}).get("dest"))
        ]
        self.assertEqual(offenders, [])

    def test_core_relays_a_staged_change_and_tolerates_a_stageless_run(
        self,
    ) -> None:
        staged = [
            task
            for task in _tasks(STAGE)
            if CHANGED in (task.get("ansible.builtin.set_fact") or {})
        ]
        self.assertEqual(len(staged), 1)
        relays = [
            task
            for task in _tasks(CORE)
            if "compose-up" in (task.get("notify") or [])
            and _whens(task, [])[:2] == [f"{CHANGED} is defined", f"{CHANGED} | bool"]
        ]
        self.assertEqual(len(relays), 1)
        self.assertEqual(
            [task for task in _tasks(CORE) if "ansible.builtin.assert" in task],
            [],
            "a sync_scope=task run enters 00_core without the stage",
        )

    def test_every_bind_source_of_access_request_exists_on_every_node(self) -> None:
        mounts = _yaml(VARS)["ACCESS_REQUEST_MOUNTS"]
        self.assertEqual(set(MOUNT_SOURCE.findall(mounts)), {CONFIG_HOST, CA_HOST})
        tls = _yaml(TLS_VARS)
        ca_trust = tls["CA_TRUST"]
        worker_root_ca = [
            (task, parents)
            for task, parents in _writers(
                CA_CORE, "ansible.builtin.copy", "dest", "CA_ROOT.cert_host"
            )
            if any(NOT_STACK_HOST.match(when) for when in _whens(task, parents))
        ]
        nfs_includes = [
            (task, parents)
            for task, parents in _scoped(COMPOSE_MAIN)
            if _spec(task, INCLUDES).get("file") == "utils/nfs_prep.yml"
        ]
        producers = {
            "config.json: replicated by the stack stage": bool(_stage_config_entries()),
            "own CA mount: gated on the global self_signed TLS mode": (
                _yaml(VARS)["ACCESS_REQUEST_CA_FILE"]
                == "{{ CA_TRUST_CERT_CONTAINER_SELFSIGNED }}"
                and SELF_SIGNED in tls["CA_TRUST_CERT_CONTAINER_SELFSIGNED"]
                and "if ACCESS_REQUEST_CA_FILE" in mounts
            ),
            "root CA: sys-ca-selfsigned on every swarm node": _ca_reaches_every_swarm_node(),
            "root CA: each worker writes its own copy": ca_trust["cert_host"]
            == "{{ CA_ROOT.cert_host }}"
            and len(worker_root_ca) == 1
            and _on_every_host(*worker_root_ca[0]),
            "CA override ca-trust-wrapper: written per host": ca_trust["wrapper_host"]
            == "{{ BIN_CA_TRUST }}"
            and _per_host_writer(
                CA_CORE, "ansible.builtin.copy", "dest", "BIN_CA_TRUST"
            ),
            "CA override ca-trust-php.ini: written per host": _per_host_writer(
                CA_CORE, "ansible.builtin.template", "dest", "CA_TRUST.php_ini_host"
            ),
            "CA override ca-bundle.crt: written per host": _per_host_writer(
                CA_CORE, "ansible.builtin.script", "cmd", "CA_TRUST.bundle_host"
            ),
            "meta/volumes.yml: named volumes only": all(
                entry.get("type", "volume") == "volume"
                for entry in _yaml(VOLUMES).values()
            ),
            "NFS volume devices: materialized on every swarm node": (
                "placement" not in _yaml(SERVICES)["access-request"]
                and len(nfs_includes) == 1
                and _whens(*nfs_includes[0]) == ["IS_SWARM_MODE"]
                and _on_every_host(*nfs_includes[0])
                and any(
                    task.get("delegate_to") == "{{ item.1 }}"
                    and "groups['svc-swarm-node']" in str(task.get("loop"))
                    and str(task["ansible.builtin.file"].get("path")).startswith(
                        "{{ DIR_VAR_LIB }}/"
                    )
                    and any("roles_with_placement" in w for w in _whens(task, []))
                    for task in _tasks(NFS_PREP)
                    if "ansible.builtin.file" in task
                )
            ),
        }
        self.assertEqual(
            [source for source, present in producers.items() if not present],
            [],
            "each bind source access-request mounts must reach every swarm node "
            "before stack deploy, or the task is rejected on a worker",
        )


if __name__ == "__main__":
    unittest.main()
