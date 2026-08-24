"""Lint: every ``container_volumes`` lookup call in a Jinja template MUST be
the canonical single-line form

    {{ lookup('container_volumes', service_name[, kwargs...]) | indent(4) }}

four spaces before the expression and ``| indent(4)`` behind it, so the
rendered mount block always lands at the service-body level. The service
position MUST be the ``service_name`` variable - a literal or role-specific
variable there bypasses the ``{% set service_name %}`` idiom the surrounding
lookups (``container_healthcheck``, ...) already rely on. Keyword arguments
such as ``extra_volumes=...`` stay allowed after ``service_name``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_CALL_ANYWHERE = re.compile(r"lookup\(\s*['\"]container_volumes['\"]")
_CANONICAL = re.compile(
    r"^    \{\{ lookup\('container_volumes', service_name"
    r"(?:, [a-zA-Z_]+=.+)?\) \| indent\(4\) \}\}$"
)


class TestContainerVolumesCallShape(unittest.TestCase):
    def test_every_call_is_canonical(self) -> None:
        findings: list[str] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            for idx, line in enumerate(content.splitlines(), start=1):
                if not _CALL_ANYWHERE.search(line):
                    continue
                if _CANONICAL.match(line):
                    continue
                findings.append(f"- {rel}:{idx}: {line.strip()}")

        if findings:
            self.fail(
                "Non-canonical `container_volumes` lookup call(s). The only "
                "valid form is\n\n"
                "    {{ lookup('container_volumes', service_name"
                "[, kwargs...]) | indent(4) }}\n\n"
                "four leading spaces, `service_name` in the service "
                "position (set it via `{% set service_name = ... %}`), and "
                "`| indent(4)`. Keyword arguments after service_name are "
                "allowed; multi-line calls are not.\n\n"
                "Offenders:\n" + "\n".join(findings)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
