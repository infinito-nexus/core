"""Flag `type: bind` entries in ``roles/<role>/meta/volumes.yml`` whose
source or any mount target points to a single FILE (path ends in a
recognised file extension or its only-Jinja form names a file-suffix
var like ``*_CONF``/``*_FILE``).

Single-file binds are swarm-fragile: the source path is only present on
the node where the file was rendered, so swarm rejects the task as
soon as it lands on a different node with ``bind source path does not
exist``. The fix is ``type: config`` so the manager loads the file at
``stack deploy`` time and swarm distributes it through raft to every
node. Compose-mode honours the same canonical entry (the
``compose_volumes`` filter renders it as a top-level ``configs:``
block; ``container_volumes`` emits the per-service reference), so the
role stays mode-agnostic.

Directory binds and kernel/runtime sources (``/var/run/docker.sock``,
``/proc``, ``/sys``, ``/dev``) are exempt — they cannot become
docker configs and stay as ``type: bind``.

A role that never deploys in swarm (``modes.swarm.enabled: false`` on
its primary entity, read through ``get_role_mode_enabled``) is exempt as
a whole: compose mounts the file on the host that rendered it.

Per-line opt-out
================
Add ``# nocheck: meta-volume-file-bind-should-be-config`` on the same
line as the entry's ``type: bind`` declaration, or on the immediately
preceding non-empty line. The opt-out MUST be accompanied by a short
``# Reason:`` comment explaining WHY this file cannot be a docker
config (rotates at runtime, multi-MB, the consumer writes back to it,
unique-per-host secret material, ...).
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VOLUMES
from utils.roles.meta_lookup import get_role_mode_enabled

from . import PROJECT_ROOT

_RULE = "meta-volume-file-bind-should-be-config"

_FILE_LIKE = re.compile(
    r"\.(?:yaml|yml|json|conf|cfg|ini|toml|lua|php|exs|env|sh|crt|key|pem|html|txt|xml|properties)$"
)
_DIRECTORY_SUFFIX_D = re.compile(r"\.d/?$")
_JINJA_VAR_ONLY = re.compile(r"^\s*\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}\s*$")
_FILE_LIKE_VAR_SUFFIX = re.compile(
    r"_(?:FILE|CONF|YAML|YML|JSON|CFG|INI|TOML|LUA|PHP|EXS|CRT|KEY|PEM|HTML|XML)(?:_|$)"
)

_SPECIAL_SOURCES_PREFIX = (
    "/var/run/",
    "/run/",
    "/proc/",
    "/sys/",
    "/dev/",
)


def _is_file_like(path: str) -> bool:
    path_trimmed = path.rstrip()
    if not path_trimmed:
        return False
    if path_trimmed.endswith("/"):
        return False
    if _DIRECTORY_SUFFIX_D.search(path_trimmed):
        return False
    if _FILE_LIKE.search(path_trimmed):
        return True
    var_only = _JINJA_VAR_ONLY.match(path_trimmed)
    return bool(var_only and _FILE_LIKE_VAR_SUFFIX.search(var_only.group(1)))


def _is_special_source(src: str) -> bool:
    src_stripped = src.strip()
    return any(src_stripped.startswith(p) for p in _SPECIAL_SOURCES_PREFIX)


def _key_line_index(lines: list[str], key: str) -> int | None:
    pattern = re.compile(rf"^{re.escape(key)}:\s*$")
    for idx, line in enumerate(lines):
        if pattern.match(line):
            return idx
    return None


def _is_file_bind(entry: object) -> bool:
    if not isinstance(entry, dict) or entry.get("type") != "bind":
        return False
    source = str(entry.get("source", ""))
    if _is_special_source(source):
        return False
    targets = [
        str(m.get("target", ""))
        for m in (entry.get("mounts") or [])
        if isinstance(m, dict)
    ]
    return _is_file_like(source) or any(_is_file_like(t) for t in targets)


def _role_findings(role_dir: Path, root: Path) -> list[tuple[str, int, str]]:
    """Args:
    role_dir: one role directory.
    root: the directory the reported paths are relative to.

    Returns:
        ``(path, line, entry)`` of every unsuppressed single-file bind of the
        role's ``meta/volumes.yml``; none for a role that never deploys in
        swarm.
    """
    meta_path = role_dir / ROLE_FILE_META_VOLUMES
    if not meta_path.is_file():
        return []
    if not get_role_mode_enabled(role_dir, mode="swarm", role_name=role_dir.name):
        return []
    try:
        entries = load_yaml_any(str(meta_path), default_if_missing={})
    except Exception:
        return []
    if not isinstance(entries, dict):
        return []
    try:
        content_lines = read_text(str(meta_path)).splitlines()
    except (OSError, ValueError):
        content_lines = []
    rel = meta_path.relative_to(root).as_posix()
    findings: list[tuple[str, int, str]] = []
    for semantic_name, entry in entries.items():
        if not _is_file_bind(entry):
            continue
        key_idx = _key_line_index(content_lines, str(semantic_name))
        line_no = (key_idx + 1) if key_idx is not None else 1
        if content_lines and is_suppressed_at(
            content_lines, line_no, _RULE, mode="same-or-above"
        ):
            continue
        findings.append((rel, line_no, str(semantic_name)))
    return findings


def _findings(roles_dir: Path) -> list[tuple[str, int, str]]:
    """Args:
    roles_dir: the directory holding the roles.

    Returns:
        The ``_role_findings`` of every role below ``roles_dir``.
    """
    return [
        finding
        for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir())
        for finding in _role_findings(role_dir, roles_dir.parent)
    ]


_PROBE_SERVICES = """\
probe:
  modes:
    compose:
      enabled: true
    swarm:
      enabled: {swarm}
"""
_PROBE_VOLUMES = """\
probe_conf:
  type: bind
  source: /etc/probe/probe.conf
  mounts:
    - service: probe
      target: /etc/probe.conf
"""


def _probe_findings(swarm: str) -> list[tuple[str, int, str]]:
    """Args:
    swarm: the ``modes.swarm.enabled`` of the probe role.

    Returns:
        The findings of one role with one single-file bind.
    """
    with tempfile.TemporaryDirectory() as scratch:
        role = Path(scratch) / "roles" / "web-app-probe"
        (role / ROLE_FILE_META_VOLUMES).parent.mkdir(parents=True)
        (role / ROLE_FILE_META_SERVICES).write_text(
            _PROBE_SERVICES.format(swarm=swarm), encoding="utf-8"
        )
        (role / ROLE_FILE_META_VOLUMES).write_text(_PROBE_VOLUMES, encoding="utf-8")
        return _findings(role.parent)


class TestMetaVolumesFileBindShouldBeConfig(unittest.TestCase):
    def test_a_role_that_never_deploys_in_swarm_is_exempt(self) -> None:
        self.assertEqual(_probe_findings("false"), [])

    def test_negative_control_a_swarm_capable_file_bind_still_fails(self) -> None:
        self.assertEqual(
            _probe_findings("true"),
            [(f"roles/web-app-probe/{ROLE_FILE_META_VOLUMES}", 1, "probe_conf")],
        )

    def test_no_file_bind_entries_in_meta_volumes(self) -> None:
        findings = _findings(PROJECT_ROOT / "roles")

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: '{s}' (type: bind to file)"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found 'type: bind' entries in meta/volumes.yml whose source "
                "or mount target points to a single file. These are swarm-"
                "fragile: the file only exists on the rendering node, so "
                "swarm rejects the task when it lands on a different node.\n\n"
                "Fix: change 'type: bind' to 'type: config'. Example:\n\n"
                "    nginx_conf:\n"
                "      type: config           # was: bind\n"
                '      source: "{{ NGINX_CONF_HOST }}"\n'
                '      mode: "0440"\n'
                "      mounts:\n"
                "        - service: openresty\n"
                "          target: /usr/local/openresty/nginx/conf/nginx.conf\n\n"
                "Compose-mode honours the same entry (renders as a bind "
                "mount under the hood), so the role stays mode-agnostic.\n\n"
                "If the file genuinely cannot be a docker config (rotates "
                "at runtime, multi-MB, the consumer writes back to it, "
                "unique-per-host material), mark with "
                f"`# nocheck: {_RULE}` plus a short # Reason: WHY.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
