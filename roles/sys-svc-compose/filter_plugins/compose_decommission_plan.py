from __future__ import annotations

from pathlib import PurePosixPath

from ansible.errors import AnsibleFilterError

from utils.docker.paths_utils import get_docker_paths
from utils.roles.entity.name import get_entity_name


def _require(name: str, value, kind) -> None:
    if not isinstance(value, kind):
        raise AnsibleFilterError(
            f"compose decommission: '{name}' has the wrong type {type(value).__name__}"
        )


def _instance_layout() -> tuple[frozenset[str], str]:
    paths = get_docker_paths("instance", "/")
    instance = PurePosixPath(paths["directories"]["instance"])
    directories = frozenset(
        PurePosixPath(path).relative_to(instance).as_posix()
        for key, path in paths["directories"].items()
        if key != "instance"
    )
    compose_file = PurePosixPath(paths["files"]["compose"]).relative_to(instance)
    return directories, compose_file.as_posix()


def compose_decommission_plan(
    entries: list[dict], root: str, active_roles: list[str], known_roles: list[str]
) -> dict[str, list[str]]:
    """Split the directories below the compositions root that no active role owns.

    Args:
        entries: ``find`` results for ``root`` down to depth 2, hidden entries
            included, symlinks not followed.
        root: ``DIR_COMPOSITIONS``.
        active_roles: every role id or group that keeps its instance.
        known_roles: every role id that can own an instance.

    Returns:
        ``stale``: the sorted unowned directories named after a known role
        that carry the full compose instance layout of ``get_docker_paths``.
        ``unmanaged``: the sorted unowned directories that miss either; the
        decommission leaves them alone.
    """
    _require("entries", entries, (list, tuple))
    _require("root", root, str)
    _require("active_roles", active_roles, (list, tuple))
    _require("known_roles", known_roles, (list, tuple))
    layout_directories, compose_file = _instance_layout()
    base = PurePosixPath(root)
    instances: set[PurePosixPath] = set()
    present: set[tuple[PurePosixPath, str, bool]] = set()
    for entry in entries:
        path = PurePosixPath(entry["path"])
        if path.parent == base:
            if entry["isdir"] and not path.name.startswith("."):
                instances.add(path)
        elif path.parent.parent == base and (entry["isdir"] or entry["isreg"]):
            present.add((path.parent, path.name, entry["isdir"]))
    owned = {get_entity_name(role) for role in active_roles}
    known = {get_entity_name(role) for role in known_roles}
    plan: dict[str, list[str]] = {"stale": [], "unmanaged": []}
    for instance in sorted(instances):
        if instance.name in owned:
            continue
        complete = (
            instance.name in known
            and (instance, compose_file, False) in present
            and all(
                (instance, directory, True) in present
                for directory in layout_directories
            )
        )
        plan["stale" if complete else "unmanaged"].append(str(instance))
    return plan


def compose_decommission_confirm(
    plan: dict[str, list[str]], namesakes: list[dict]
) -> dict[str, list[str]]:
    """Keep the stale instances whose name a container outside their project holds.

    Args:
        plan: the result of ``compose_decommission_plan``.
        namesakes: the registered loop results of ``container ps --all`` per
            stale instance, filtered on the instance name and formatted as
            ``<names> <compose project label>``.

    Returns:
        ``plan`` with ``stale`` reduced to the instances no foreign container
        is named after and ``foreign`` listing the ones it holds back.
    """
    _require("plan", plan, dict)
    _require("namesakes", namesakes, (list, tuple))
    foreign = set()
    for result in namesakes:
        instance = result[result["ansible_loop_var"]]
        name = PurePosixPath(instance).name
        for line in result["stdout_lines"]:
            if line.partition(" ")[2].strip() != name:
                foreign.add(instance)
    return {
        "stale": [instance for instance in plan["stale"] if instance not in foreign],
        "unmanaged": plan["unmanaged"],
        "foreign": sorted(foreign),
    }


class FilterModule:
    def filters(self):
        return {
            "compose_decommission_plan": compose_decommission_plan,
            "compose_decommission_confirm": compose_decommission_confirm,
        }
