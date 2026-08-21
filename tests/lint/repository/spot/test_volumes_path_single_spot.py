"""Forbid repeating a container path that ``meta/volumes.yml`` already declares.

``meta/volumes.yml`` says where a volume lands inside its container. Once a
second file spells the same path out, the two drift independently: the mount
moves, the consumer keeps pointing at the old place, and nothing fails until
the process looks for content that is not there.

The registry is readable, so a role derives instead of repeating:

    PROMETHEUS_CONFIG_FILE: "{{ lookup('volume', application_id, 'prometheus_config').target }}"

``target`` exists when every mount of that entry agrees; an entry that lands at
different paths per service exposes ``targets[service]`` instead.

Scope: role files Ansible renders -- ``vars/``, ``tasks/``, ``templates/`` and
the rest of ``meta/``. Two areas are out by construction:

* ``roles/*/files/`` is copied verbatim into an image and executed there, with
  no Ansible in sight, so a Dockerfile or an entrypoint cannot evaluate a
  lookup. Those sites carry a per-line opt-out instead.
* ``.md`` documentation names paths in prose.

A path is only flagged where it stands alone; ``/srv/app`` inside ``/srv/app/data``
is a different path and is left untouched.

Per-line opt-out: ``# nocheck: volumes-path-single-spot`` on the offending line
or the immediately preceding non-empty line, with the reason it cannot derive.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_non_ignored_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

_RULE = "volumes-path-single-spot"
_MIN_PATH_LEN = 7
_SKIP_AREAS = ("files",)
_BOUNDARY = re.compile(r"[\w./-]")


def _unambiguous_targets(volumes_path: Path) -> dict[str, str]:
    """Map container path -> semantic key, for entries with one target only.

    Args:
        volumes_path: the role's ``meta/volumes.yml``.
    """
    doc = load_yaml_any(str(volumes_path), default_if_missing={}) or {}
    if not isinstance(doc, dict):
        return {}
    out: dict[str, str] = {}
    for key, entry in doc.items():
        if not isinstance(entry, dict):
            continue
        targets = {
            mount.get("target")
            for mount in (entry.get("mounts") or [])
            if isinstance(mount, dict) and isinstance(mount.get("target"), str)
        }
        if len(targets) != 1:
            continue
        target = next(iter(targets))
        if target.startswith("/") and len(target) >= _MIN_PATH_LEN:
            out[target] = key
    return out


def _hits(lines: list[str], targets: dict[str, str]) -> list[tuple[int, str, str]]:
    """Lines that spell out a declared path as a standalone value."""
    found: list[tuple[int, str, str]] = []
    for idx, line in enumerate(lines):
        for target, key in targets.items():
            start = line.find(target)
            if start < 0:
                continue
            # Exception: a relative path whose tail equals the target is not the
            # target - `src: shell/entrypoint.sh` ends in `/entrypoint.sh` but
            # names a role-local file, not the container mount.
            before = line[start - 1 : start] if start else ""
            if before and _BOUNDARY.match(before):
                continue
            after = line[start + len(target) : start + len(target) + 1]
            if after and _BOUNDARY.match(after):
                continue
            if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                continue
            found.append((idx + 1, target, key))
            break
    return found


class TestVolumesPathSingleSpot(unittest.TestCase):
    def test_declared_paths_are_derived_not_repeated(self) -> None:
        findings: list[str] = []
        for volumes_path in sorted(
            PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_VOLUMES}")
        ):
            role_dir = volumes_path.parent.parent
            targets = _unambiguous_targets(volumes_path)
            if not targets:
                continue
            for path_str in iter_non_ignored_files(exclude_tests=True):
                path = Path(path_str)
                if role_dir not in path.parents or path == volumes_path:
                    continue
                rel_in_role = path.relative_to(role_dir)
                if rel_in_role.parts[0] in _SKIP_AREAS or path.suffix == ".md":
                    continue
                try:
                    lines = read_text(path_str).splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for line_no, target, key in _hits(lines, targets):
                    rel = path.relative_to(PROJECT_ROOT).as_posix()
                    findings.append(
                        f"- {rel}:{line_no}: {target}  (declared as {key!r})"
                    )

        if not findings:
            return

        self.fail(
            "A container path declared in meta/volumes.yml is written out again. "
            "Derive it from the registry so the mount and its consumer cannot "
            "drift apart:\n\n"
            "    \"{{ lookup('volume', application_id, '<key>').target }}\"\n\n"
            + "\n".join(sorted(set(findings)))
            + f"\n\nPer-line opt-out: `# nocheck: {_RULE}` with the reason it "
            "cannot derive."
        )


if __name__ == "__main__":
    unittest.main()
