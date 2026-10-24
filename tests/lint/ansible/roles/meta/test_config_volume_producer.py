"""Flag `type: config` entries in ``roles/<role>/meta/volumes.yml`` whose
source file nothing produces.

A config entry mounts a file the role renders or copies onto the stack host.
When the template, the static file or the task that writes it goes away while
the entry stays, compose fails at ``up`` with ``bind source path does not
exist`` and swarm fails at ``stack deploy``, both long after the lint stage.

An entry counts as produced when the file name its ``source`` ends in, read
literally or through the role or global variable it names, appears in an
owning role as ``files/**/<name>``, ``templates/**/<name>[.j2]``, or in the
text of its ``tasks``, ``handlers``, ``vars``, ``defaults`` or
``meta/services.yml``. A role whose tasks call ``design_assets``, directly or
by handing ``design_assets_dest`` to ``sys-front-inj-design``'s
``assets.yml``, also produces ``favicon.ico`` and ``<slot>.png``/``<slot>.svg``
for every slot it or ``web-svc-design``'s defaults name. A name carrying a
network label (``<stem>-<label>.<ext>``, see ``labelled_file``) is produced
when its unlabelled name is. The owning roles are the role itself and every
role a ``lookup('container', '<role>', …)`` in the source names. A source that
is a global variable is produced centrally, so every role counts as an owner.

Per-line opt-out
================
Add ``# nocheck: config-volume-producer`` with a reason on the entry's key
line or on the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.networks.reachability import NETWORKS
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

_RULE = "config-volume-producer"
_LABELS = tuple(network.label for network in NETWORKS.values() if network.label)
_DESIGN_ASSETS_TASK = re.compile(r"^\s*design_assets(?:_dest)?:", re.MULTILINE)
_DESIGN_ASSET_FAVICON = "favicon.ico"
_DESIGN_ASSET_SUFFIXES = (".png", ".svg")
_DESIGN_PROVIDER = "web-svc-design"
_SHIPPED_DIRS = ("files", "templates")
_PRODUCER_DIRS = ("tasks", "handlers", "vars", "defaults")
_VARIABLE_DIRS = ("vars", "defaults")

_LAST_LITERAL = re.compile(
    r"""['"]([^'"/{}]+\.[A-Za-z0-9]+)['"]\s*\]\s*\|\s*path_join"""
)
_PLAIN_PATH = re.compile(r"""/([^/'"{}\s]+\.[A-Za-z0-9]+)\s*"?\s*$""")
_VAR_ONLY = re.compile(r"""^\s*"?\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}"?\s*$""")
_CONTAINER_OWNER = re.compile(
    r"""lookup\(\s*['"]container['"]\s*,\s*['"]([a-z0-9-]+)['"]"""
)


class _Tree:
    """The role files of one project tree, grouped by role.

    Args:
        root: the directory holding ``roles`` and ``group_vars``.
        files: absolute paths of every file below ``root`` to consider.
    """

    def __init__(self, root: Path, files: list[str]) -> None:
        self.shipped: dict[str, set[str]] = defaultdict(set)
        self.texts: dict[str, list[str]] = defaultdict(list)
        self.variables: dict[str, list[str]] = defaultdict(list)
        self.volumes: dict[str, str] = {}
        self.group_vars: list[str] = []
        services = Path(ROLE_FILE_META_SERVICES).parts
        volumes = Path(ROLE_FILE_META_VOLUMES).parts
        for path in sorted(files):
            parts = Path(path).relative_to(root).parts
            if parts[0] == "group_vars" and path.endswith(".yml"):
                self.group_vars.append(path)
            if parts[0] != "roles" or len(parts) < 3:
                continue
            role, rest = parts[1], parts[2:]
            if rest == volumes:
                self.volumes[role] = path
            elif rest[0] in _SHIPPED_DIRS:
                self.shipped[role].add(rest[-1])
            elif rest == services or (
                rest[0] in _PRODUCER_DIRS and path.endswith(".yml")
            ):
                self.texts[role].append(read_text(path))
                if rest[0] in _VARIABLE_DIRS:
                    self.variables[role].append(path)

    def roles(self) -> list[str]:
        return sorted(self.volumes)

    def all_roles(self) -> list[str]:
        return sorted({*self.shipped, *self.texts, *self.volumes})


def _file_name(source: str) -> str | None:
    """Return the file name a source path ends in.

    Args:
        source: the raw ``source`` value of a volume entry.

    Returns:
        The trailing file name, or None when the source names no literal file.
    """
    literal = _LAST_LITERAL.search(source)
    if literal:
        return literal.group(1)
    plain = _PLAIN_PATH.search(source)
    return plain.group(1) if plain else None


def _variable_value(tree: _Tree, role: str, name: str) -> tuple[str, bool] | None:
    """Return the raw value of a variable and whether it is global.

    Args:
        tree: the indexed project tree.
        role: the role declaring the volume.
        name: the variable the source consists of.

    Returns:
        ``(value, is_global)``, or None when no vars, defaults or group_vars
        file declares the variable.
    """
    pattern = re.compile(rf"^{re.escape(name)}:\s*(.+)$", re.MULTILINE)
    for path in tree.variables[role]:
        match = pattern.search(read_text(path))
        if match:
            return match.group(1), False
    for path in tree.group_vars:
        match = pattern.search(read_text(path))
        if match:
            return match.group(1), True
    return None


def _unlabelled(name: str) -> str | None:
    """Return the name a network label was appended to, if any.

    Args:
        name: a file name such as ``config-onion.yaml``.
    """
    stem, dot, extension = name.rpartition(".")
    for label in _LABELS:
        if dot and stem.endswith(f"-{label}"):
            return f"{stem[: -len(label) - 1]}.{extension}"
    return None


def _produced_in(tree: _Tree, role: str, name: str) -> bool:
    """Return whether a role ships or writes a file of the given name.

    Args:
        tree: the indexed project tree.
        role: the owning role.
        name: the file name the volume source ends in.
    """
    if name in tree.shipped[role] or f"{name}.j2" in tree.shipped[role]:
        return True
    texts = tree.texts[role]
    if any(name in text for text in texts):
        return True
    if not any(_DESIGN_ASSETS_TASK.search(text) for text in texts):
        return False
    stem, _, _ = name.rpartition(".")
    slot_texts = [*texts, *tree.texts[_DESIGN_PROVIDER]]
    return name == _DESIGN_ASSET_FAVICON or (
        name.endswith(_DESIGN_ASSET_SUFFIXES)
        and any(stem in text for text in slot_texts)
    )


def unproduced_config_volumes(
    root: Path, files: list[str]
) -> list[tuple[str, int, str, str]]:
    """Return every unsuppressed config entry whose source nothing produces.

    Args:
        root: the directory holding ``roles`` and ``group_vars``.
        files: absolute paths of every file below ``root`` to consider.

    Returns:
        ``(volumes file, line, entry name, file name)`` per offender.
    """
    tree = _Tree(root, files)
    findings: list[tuple[str, int, str, str]] = []
    for role in tree.roles():
        meta_path = tree.volumes[role]
        entries = load_yaml_any(meta_path, default_if_missing={})
        if not isinstance(entries, dict):
            continue
        lines = read_text(meta_path).splitlines()
        for entry_name, entry in entries.items():
            if not isinstance(entry, dict) or entry.get("type") != "config":
                continue
            source = str(entry.get("source", ""))
            owners = {role}
            variable = _VAR_ONLY.match(source)
            if variable:
                resolved = _variable_value(tree, role, variable.group(1))
                if resolved is None:
                    continue
                source, is_global = resolved
                if is_global:
                    owners = set(tree.all_roles())
            name = _file_name(source)
            if name is None:
                continue
            owners.update(_CONTAINER_OWNER.findall(source))
            candidates = [n for n in (name, _unlabelled(name)) if n]
            if any(
                _produced_in(tree, owner, candidate)
                for owner in sorted(owners)
                for candidate in candidates
            ):
                continue
            line = next(
                (
                    n
                    for n, text in enumerate(lines, 1)
                    if text.startswith(f"{entry_name}:")
                ),
                1,
            )
            if is_suppressed_at(lines, line, _RULE, mode="same-or-above"):
                continue
            findings.append((meta_path, line, str(entry_name), name))
    return findings


class TestConfigVolumeProducer(unittest.TestCase):
    def test_every_config_volume_has_a_producer(self) -> None:
        findings = unproduced_config_volumes(PROJECT_ROOT, list(iter_project_files()))
        if findings:
            formatted = "\n".join(
                f"- {Path(path).relative_to(PROJECT_ROOT).as_posix()}:{line}: "
                f"'{entry}' mounts '{name}', which no template, file or task produces"
                for path, line, entry, name in findings
            )
            self.fail(
                "Found 'type: config' entries whose source file nothing "
                "produces. compose fails at 'up' with 'bind source path does "
                "not exist' and swarm at 'stack deploy'.\n\n"
                "Fix: remove the entry, or restore the template, file or task "
                "that writes its source. If the file is produced in a way this "
                f"lint cannot see, mark the entry with `# nocheck: {_RULE}` and "
                f"a reason.\n\nOffenders:\n{formatted}"
            )

    def test_an_entry_whose_producer_is_gone_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meta = root / "roles" / "web-app-demo" / ROLE_FILE_META_VOLUMES
            meta.parent.mkdir(parents=True)
            meta.write_text(
                "entrypoint:\n"
                "  type: config\n"
                "  source: \"{{ [lookup('container', 'web-app-demo', "
                "'directories.instance'), 'docker-entrypoint.sh'] | path_join }}\"\n"
                "  mounts:\n"
                "    - service: demo\n"
                "      target: /entrypoint.sh\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [(str(meta), 1, "entrypoint", "docker-entrypoint.sh")],
                unproduced_config_volumes(root, [str(meta)]),
            )
            template = (
                root
                / "roles"
                / "web-app-demo"
                / "templates"
                / "docker-entrypoint.sh.j2"
            )
            template.parent.mkdir(parents=True)
            template.write_text("#!/bin/sh\n", encoding="utf-8")
            self.assertEqual(
                [], unproduced_config_volumes(root, [str(meta), str(template)])
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
