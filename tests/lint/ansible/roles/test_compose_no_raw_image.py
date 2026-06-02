"""Lint compose templates for raw (hard-coded) ``image:`` references.

Every ``roles/<role>/templates/compose.yml.j2`` line of the form
``image: <value>`` MUST resolve through a Jinja substitution
(``{{ ... }}``) so that the underlying registry / repository / tag is
declared in the role's ``meta/services.yml`` (or sourced from a central
image provider) instead of being pinned in the compose template.

A raw line such as::

    image: taigaio/taiga-events:latest

bypasses ``meta/services.yml``: there is no per-service ``version`` knob,
no central image override, and no audit trail for upgrades. The fix is
to declare the service (with its ``version`` / image attributes) in
``meta/services.yml`` and render the image via a templated variable.

This rule is in strict mode: any new raw ``image:`` reference fails the
build.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.message import in_github_actions, warning
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

COMPOSE_TEMPLATE = ROLE_FILE_TEMPL_COMPOSE

IMAGE_LINE_RE = re.compile(r"^(?P<indent>\s*)image:\s*(?P<value>\S.*?)\s*$")


@dataclass(frozen=True)
class RawImageFinding:
    role: str
    template_path: Path
    line: int
    image: str


def _is_raw(image_value: str) -> bool:
    """A raw image has no Jinja substitution anywhere in the value.

    ``image: taigaio/taiga-events:latest`` → raw.
    ``image: "{{ TAIGA_IMAGE }}:{{ TAIGA_VERSION }}"`` → not raw.
    ``image: {{ MAILU_FLAVOR }}/nginx:{{ MAILU_VERSION }}`` → not raw.

    Strip surrounding quotes first so quoted-but-templated values
    (``"{{ X }}"``) are correctly recognised as templated.
    """
    stripped = image_value.strip().strip('"').strip("'")
    return "{{" not in stripped


def _collect_findings(root: Path) -> list[RawImageFinding]:
    findings: list[RawImageFinding] = []
    roles_dir = root / "roles"
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        template_path = role_dir / COMPOSE_TEMPLATE
        if not template_path.is_file():
            continue

        try:
            content = read_text(str(template_path))
        except OSError:
            continue

        for lineno, raw_line in enumerate(content.splitlines(), start=1):
            match = IMAGE_LINE_RE.match(raw_line)
            if not match:
                continue
            value = match.group("value")
            if _is_raw(value):
                findings.append(
                    RawImageFinding(
                        role=role_dir.name,
                        template_path=template_path,
                        line=lineno,
                        image=value,
                    )
                )

    findings.sort(key=lambda f: (f.role, f.line))
    return findings


def _emit_warning(finding: RawImageFinding, root: Path) -> None:
    rel = finding.template_path.relative_to(root).as_posix()
    warning(
        f"{finding.role}: raw image `{finding.image}` must be declared in "
        f"meta/services.yml and rendered via a Jinja substitution",
        title="Raw image in compose template",
        file=rel,
        line=finding.line,
    )


def _print_summary(findings: list[RawImageFinding], root: Path) -> None:
    if not findings:
        return
    print()
    print(f"[WARNING] Raw image references in compose templates ({len(findings)}):")
    for f in findings:
        rel = f.template_path.relative_to(root).as_posix()
        print(f"- {rel}:{f.line} - image: {f.image} ({f.role})")


class TestComposeNoRawImage(unittest.TestCase):
    def test_compose_images_resolve_via_services_yml(self) -> None:
        """Fail on any raw ``image:`` line across every role's compose template."""
        root = PROJECT_ROOT
        findings = _collect_findings(root)

        for finding in findings:
            _emit_warning(finding, root)

        if not in_github_actions():
            _print_summary(findings, root)

        details = "\n".join(
            f"- {f.template_path.relative_to(root).as_posix()}:{f.line}"
            f" - image: {f.image} ({f.role})"
            for f in findings
        )
        self.assertEqual(
            len(findings),
            0,
            f"Raw `image:` references found ({len(findings)}). Each must be "
            f"declared in the role's meta/services.yml and rendered via a "
            f"Jinja substitution:\n{details}",
        )


if __name__ == "__main__":
    unittest.main()
