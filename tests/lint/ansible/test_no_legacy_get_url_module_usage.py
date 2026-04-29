from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content


def repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("Repository root not found from test path.")


LEGACY_GET_URL_MODULE_PATTERN = re.compile(
    r"^\s*(ansible\.builtin\.get_url|get_url)\s*:\s*(?:#.*)?$"
)


class TestNoLegacyGetUrlModuleUsage(unittest.TestCase):
    REPO_ROOT = repo_root()

    def test_no_legacy_get_url_module_call_is_used(self):
        """
        Enforce migration from legacy get_url module calls to get_url_retry.
        """
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            yml_file = Path(path_str)
            rel = yml_file.relative_to(self.REPO_ROOT).as_posix()
            for line_no, line in enumerate(content.splitlines(), start=1):
                if LEGACY_GET_URL_MODULE_PATTERN.match(line):
                    findings.append((rel, line_no, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    findings, key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found legacy get_url module calls in .yml files.\n\n"
                "Please migrate all of them to `get_url_retry:` so deploys are resilient against "
                "transient network outages.\n\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
