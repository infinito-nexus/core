"""Flag raw ``image:`` references in role templates.

Every Docker image pulled into a service definition MUST resolve via
``lookup('container_image', application_id, '<service_key>')`` so the
image registry, repository, and tag are sourced from the central
``container_image`` lookup plugin (single source of truth, swarm-aware
digest pinning, mirror fallback). A raw ``"{{ FOO_IMAGE }}:{{ FOO_VERSION }}"``
or hard-coded string bypasses that and silently drifts away from the
project-wide image-resolution policy.

Compliant shape
===============

Only one form is accepted: a standalone Jinja line that is *only*
``{{ lookup('container_image', application_id, '<service_key>') }}``.
The lookup itself emits the wrapping ``image: "..."``, so the
template no longer carries an explicit ``image:`` key. The lint
regex below does not match such lines at all (they have no
``image:`` prefix), so they are silently skipped.

Scan target
===========

Every ``.yml.j2`` / ``.yaml.j2`` file under ``roles/*/templates/``
(recursive). Covers ``compose.yml.j2``, sibling files like
``services.yml.j2``, nested flavor files such as
``templates/flavor/compose/services.yml.j2``, plus less-common shapes
like ``services/<name>.yml.j2``, ``compose-inits.yml.j2``, and
``sso_proxy/container.yml.j2``. The ``image:`` regex naturally limits
findings to docker-compose-style image keys.

Flagged
=======

Any line matching ``^(?P<indent>\\s*)image\\s*:\\s*<value>`` with a
non-empty value. Commented-out ``# image: ...`` lines, keys that
merely *contain* the substring "image" (e.g. ``OPENLDAP_IMAGE:``),
and standalone lookup lines (compliant shape, no ``image:`` prefix)
are not flagged.

Suppression
===========

* Per-line: ``# nocheck: container-image-lookup`` on the offending
  line OR on the immediately preceding non-empty line.
* File-level: ``# nocheck: container-image-lookup`` anywhere in the
  first 30 lines of the template (for compose files where every image
  is legitimately raw, e.g. a local build with no registry image).
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "container-image-lookup"

_IMAGE_LINE = re.compile(r"^(?P<indent>\s*)image\s*:\s*(?P<value>.*?)\s*$")
_TEMPLATE_SUFFIXES = (".yml.j2", ".yaml.j2")


@dataclass(frozen=True)
class Finding:
    rel_path: str
    line_no: int
    raw_line: str
    indent: str


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/") or "/templates/" not in rel_path:
        return False
    return rel_path.endswith(_TEMPLATE_SUFFIXES)


def _scan_content(rel_path: str, content: str) -> list[Finding]:
    lines = content.splitlines()
    if is_suppressed_in_head(lines, _RULE):
        return []

    findings: list[Finding] = []
    for idx, raw in enumerate(lines):
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            continue
        match = _IMAGE_LINE.match(raw)
        if not match:
            continue
        value = match.group("value")
        if not value:
            continue
        if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
            continue
        findings.append(
            Finding(
                rel_path=rel_path,
                line_no=idx + 1,
                raw_line=raw.rstrip(),
                indent=match.group("indent"),
            )
        )
    return findings


class TestNoRawImageInComposeTemplates(unittest.TestCase):
    def test_image_must_route_through_container_image_lookup(self) -> None:
        findings: list[Finding] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            findings.extend(_scan_content(rel, content))

        if not findings:
            return

        findings.sort(key=lambda f: (f.rel_path, f.line_no))
        suggestion = "{{ lookup('container_image', application_id, '<service_key>') }}"
        body_blocks = [
            "\n".join(
                (
                    f"- {f.rel_path}:{f.line_no}:",
                    f.raw_line,
                    f"{f.indent}^ should be: {suggestion}",
                )
            )
            for f in findings
        ]
        body = "\n\n".join(body_blocks)
        self.fail(
            f"Found {len(findings)} compose template(s) using raw `image:` "
            "refs instead of `lookup('container_image', ...)`:\n\n"
            f"{body}"
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
