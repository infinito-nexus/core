from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

RETRY_WRAPPERS: dict[str, str] = {
    "get_url": "get_url_retry",
    "uri": "uri_retry",
}

LEGACY_HTTP_MODULE_PATTERN = re.compile(
    r"^\s*(?:ansible\.builtin\.)?(?P<module>get_url|uri)\s*:\s*(?:#.*)?$"
)


def legacy_module_calls(rel: str, content: str) -> list[tuple[str, str, int, str]]:
    """Find legacy HTTP module calls in one YAML file.

    Args:
        rel: project-relative POSIX path used in the findings.
        content: text of the file.

    Returns:
        ``(module, path, line_no, line)`` per call of ``get_url`` / ``uri``.
    """
    return [
        (match["module"], rel, line_no, line.strip())
        for line_no, line in enumerate(content.splitlines(), start=1)
        if (match := LEGACY_HTTP_MODULE_PATTERN.match(line))
    ]


class TestNoLegacyHttpModuleUsage(unittest.TestCase):
    def test_no_legacy_http_module_call_is_used(self):
        findings: list[tuple[str, str, int, str]] = []
        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            findings.extend(legacy_module_calls(rel, content))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet} -> {RETRY_WRAPPERS[module]}:"
                for module, path, line_no, snippet in sorted(
                    findings, key=lambda item: (item[1], item[2])
                )
            )
            self.fail(
                "Found legacy get_url / uri module calls in .yml files.\n\n"
                "Please migrate all of them to `get_url_retry:` / `uri_retry:` "
                "so deploys are resilient against transient network outages.\n\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
