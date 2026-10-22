"""Lint: every proxying location the front proxy includes strips upstream headers.

``proxy_hide_header`` is replaced, not merged, by a location that sets its own,
so ``upstream_strips.conf.j2`` only takes effect where a location includes it.
A location fragment without it leaks ``X-Powered-By`` and the upstream's
``Strict-Transport-Security`` on that path alone.

Scope: role templates without a ``server`` block. Those are the fragments the
front proxy renders into a vhost; a template with its own ``server`` block is
the config of an app-internal nginx that sits behind such a location.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_STRIPS = "roles/sys-svc-proxy/templates/headers/upstream_strips.conf.j2"
_SERVER_BLOCK = re.compile(r"^\s*server\s*\{", re.MULTILINE)
_LOCATION_OPEN = re.compile(r"^\s*location\b[^{]*\{\s*$")
_PROXYING = re.compile(r"\bproxy_pass\b|lookup\('proxy_pass'|_backend\s*\}\}")


def _role_templates() -> list[str]:
    return sorted(
        path
        for path in iter_project_files(extensions=(".j2",), exclude_tests=True)
        if "/roles/" in path and "/templates/" in path
    )


def _location_blocks(lines: list[str]) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if not _LOCATION_OPEN.match(lines[index]):
            index += 1
            continue
        start = index
        depth = lines[index].count("{") - lines[index].count("}")
        body: list[str] = []
        index += 1
        while index < len(lines) and depth > 0:
            depth += lines[index].count("{") - lines[index].count("}")
            body.append(lines[index])
            index += 1
        blocks.append((start + 1, "\n".join(body)))
    return blocks


class TestProxyLocationStrips(unittest.TestCase):
    def test_at_least_one_fragment_is_checked(self) -> None:
        """Otherwise the assertion below passes over an empty list."""
        checked = [
            path
            for path in _role_templates()
            if not _SERVER_BLOCK.search(read_text(path))
            and any(
                _PROXYING.search(body)
                for _, body in _location_blocks(read_text(path).splitlines())
            )
        ]
        self.assertTrue(checked, "no proxying location fragment found to check")

    def test_proxying_locations_include_the_strips(self) -> None:
        findings: list[str] = []
        for path in _role_templates():
            text = read_text(path)
            if _SERVER_BLOCK.search(text):
                continue
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            for line, body in _location_blocks(text.splitlines()):
                if _PROXYING.search(body) and _STRIPS not in body:
                    findings.append(f"- {rel}:{line}")
        if findings:
            self.fail(
                "These proxying locations do not include the upstream header strips, "
                "so X-Powered-By and the upstream HSTS leak on their path:\n"
                + "\n".join(findings)
                + f"\n\nFix: add `{{% include '{_STRIPS}' %}}` inside each location."
            )


if __name__ == "__main__":
    unittest.main()
