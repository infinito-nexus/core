from __future__ import annotations

import re

from ansible.errors import AnsibleFilterError

_PARTS = ("MAJOR", "MINOR", "PATCH")
_BRIDGE_KEYS = ("version", "sha256", "plugins")
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_DATABASE_VERSION = re.compile(r"^database-version=(\S+)$", re.MULTILINE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PLUGIN = re.compile(r"^[a-z0-9_-]+/[a-z0-9_-]+$")


def _parse(version) -> tuple[int, int, int]:
    match = _VERSION.match(str(version))
    if match is None:
        raise AnsibleFilterError(
            f"'{version}' is not a Joomla core version of the form MAJOR.MINOR.PATCH"
        )
    return tuple(int(part) for part in match.groups())


def _render(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def joomla_core_version(version_php) -> str:
    """Return the ``MAJOR.MINOR.PATCH`` a ``Version.php`` declares.

    Args:
        version_php: the text of ``libraries/src/Version.php``.

    Returns:
        The version of the core files, for example ``5.3.4``.
    """
    if not isinstance(version_php, str) or not version_php.strip():
        raise AnsibleFilterError("joomla_core_version expects the text of Version.php")
    numbers = []
    for part in _PARTS:
        match = re.search(rf"\bconst\s+{part}_VERSION\s*=\s*(\d+)\s*;", version_php)
        if match is None:
            raise AnsibleFilterError(f"Version.php declares no {part}_VERSION")
        numbers.append(int(match.group(1)))
    return _render(tuple(numbers))


def joomla_core_database_version(output) -> str:
    """Return the core version the database was last finalised for.

    Args:
        output: stdout of ``core_update.php version``, whose
            ``database-version=<version>`` line carries the version that
            ``files_joomla`` records in its manifest cache.

    Returns:
        That version, for example ``5.3.4``.
    """
    matches = _DATABASE_VERSION.findall(output if isinstance(output, str) else "")
    if len(matches) != 1:
        raise AnsibleFilterError(
            "expected exactly one database-version=<version> line from core_update.php"
        )
    return _render(_parse(matches[0]))


def _bridges_by_major(bridges) -> dict[int, dict]:
    if not isinstance(bridges, list):
        raise AnsibleFilterError("the Joomla bridge releases must be a list")
    by_major: dict[int, dict] = {}
    for bridge in bridges:
        if not isinstance(bridge, dict) or set(bridge) != set(_BRIDGE_KEYS):
            raise AnsibleFilterError(
                f"a Joomla bridge release needs exactly {', '.join(_BRIDGE_KEYS)}: {bridge}"
            )
        version = _parse(bridge["version"])
        if not _SHA256.match(str(bridge["sha256"])):
            raise AnsibleFilterError(
                f"Joomla bridge {_render(version)} carries no SHA-256 of its update package"
            )
        plugins = bridge["plugins"]
        if not isinstance(plugins, dict) or not all(
            _PLUGIN.match(str(name)) and isinstance(state, bool)
            for name, state in plugins.items()
        ):
            raise AnsibleFilterError(
                f"Joomla bridge {_render(version)} needs plugins as folder/element: true|false"
            )
        if version[0] in by_major:
            raise AnsibleFilterError(
                f"two Joomla bridge releases are declared for major {version[0]}"
            )
        by_major[version[0]] = {
            "version": version,
            "sha256": str(bridge["sha256"]),
            "plugins": dict(plugins),
        }
    return by_major


def _step(origin, version, bridge, plugins) -> dict:
    return {
        "from": _render(origin),
        "version": _render(version),
        "package": bridge is not None,
        "sha256": bridge["sha256"] if bridge else "",
        "plugins": [f"{name}={int(state)}" for name, state in plugins.items()],
        "check": True,
    }


def joomla_core_upgrade_steps(database, files, target, bridges) -> list[dict]:
    """Plan the core updates that bring the site up to ``target``.

    Every step lays the files of its version over the code volume and then
    finalises the database for it, so the plan starts at the version the
    database was last finalised for. A volume whose files moved past that
    point in an interrupted update gets those files laid again. A core at
    or above ``target`` is left alone.

    Args:
        database: core version the database was last finalised for.
        files: core version of the files in the code volume.
        target: core version the pinned image ships.
        bridges: list of ``{version, sha256, plugins}``, one per major the
            core may leave. Joomla carries a major's schema changes only in
            that major's packages, so a major is left from its bridge release
            alone. ``sha256`` names the bridge's update package, ``plugins``
            the ``folder/element: enabled`` states Joomla demands before the
            major is left.

    Returns:
        Ordered steps ``{from, version, package, sha256, plugins, check}``.
        A step with ``package`` true installs that bridge's update package,
        the others the image's own tree; ``plugins`` lists
        ``folder/element=0|1`` only on the step that leaves a major; ``check``
        is false where the files in the volume no longer match ``from``, so
        the pre-update schema check of the old code cannot run.
    """
    start = current = _parse(database)
    laid = _parse(files)
    goal = _parse(target)
    by_major = _bridges_by_major(bridges)
    if max(current, laid) > goal:
        if current != laid:
            raise AnsibleFilterError(
                f"the Joomla code volume holds {_render(laid)} but the database was "
                f"finalised for {_render(current)}, and the pinned image ships "
                f"{_render(goal)}; finish that update inside Joomla, the deploy never "
                "lays older files"
            )
        return []
    steps: list[dict] = []
    while current[0] < goal[0]:
        bridge = by_major.get(current[0])
        if bridge is None:
            raise AnsibleFilterError(
                f"no bridge release is declared for Joomla {current[0]}.x, so "
                f"{_render(current)} has no update path to {_render(goal)}"
            )
        if current < bridge["version"]:
            steps.append(_step(current, bridge["version"], bridge, {}))
            current = bridge["version"]
        landing = by_major.get(current[0] + 1)
        if current[0] + 1 == goal[0]:
            steps.append(_step(current, goal, None, bridge["plugins"]))
            current = goal
        elif landing is None:
            raise AnsibleFilterError(
                f"no bridge release is declared for Joomla {current[0] + 1}.x, so "
                f"{_render(current)} has no update path to {_render(goal)}"
            )
        else:
            steps.append(_step(current, landing["version"], landing, bridge["plugins"]))
            current = landing["version"]
    if current < goal or (not steps and laid != goal):
        steps.append(_step(current, goal, None, {}))
    if steps:
        steps[0]["check"] = laid == start
    return steps


class FilterModule:
    def filters(self):
        return {
            "joomla_core_version": joomla_core_version,
            "joomla_core_database_version": joomla_core_database_version,
            "joomla_core_upgrade_steps": joomla_core_upgrade_steps,
        }
