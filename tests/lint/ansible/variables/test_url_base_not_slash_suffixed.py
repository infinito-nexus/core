"""A ``url.base`` value already ends in a slash, so nothing may append one.

Rationale
=========
``plugins/lookup/tls.py`` builds ``url.base`` as
``f"{web_protocol}://{primary_domain}/"``, and
``tests/unit/python/plugins/lookup/test_tls.py`` pins the trailing slash.
Writing ``{{ SOME_URL }}/`` therefore yields ``https://host//``.

That is not cosmetic. Consumers differ in whether they normalise: the Nextcloud
ONLYOFFICE connector normalises ``DocumentServerUrl`` but returns
``DocumentServerInternalUrl`` raw, and the swarm vhost forwards
``$request_uri`` verbatim while the compose vhost lets nginx collapse the
double slash. So the same declaration works in one deployment mode and 404s in
the other, and the 404 sets a sticky ``settings_error`` that no redeploy clears.

Per-line opt-out
================
Add ``# nocheck: url-base-not-slash-suffixed`` on the offending line or the one
above it, with a comment naming why the extra slash is wanted.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "url-base-not-slash-suffixed"

_URL_BASE = re.compile(r"lookup\(\s*['\"]tls['\"].*url\.base", re.DOTALL)
_STRIPS_SLASH = re.compile(r"regex_replace\(\s*['\"]/\+\$|trim\(\s*['\"]/")


def _is_var_file(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and (
        "/vars/" in rel_path or "/defaults/" in rel_path
    )


def _base_url_variables() -> set[str]:
    """Variable names that carry a tls ``url.base`` with its slash intact.

    A definition that strips the trailing slash again (``regex_replace('/+$')``)
    is excluded: appending a path to those is correct.
    """
    names: set[str] = set()
    for path_str, _content in iter_project_files_with_content(
        extensions=(".yml", ".yaml")
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not _is_var_file(rel):
            continue
        try:
            data = load_yaml_any(path_str, default_if_missing={}) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if _URL_BASE.search(value) and not _STRIPS_SLASH.search(value):
                names.add(key)
    return names


class TestUrlBaseNotSlashSuffixed(unittest.TestCase):
    def test_no_slash_follows_a_url_base_variable(self) -> None:
        names = _base_url_variables()
        self.assertTrue(
            names, "no tls url.base variable found; the scan would be vacuous"
        )
        pattern = re.compile(
            r"\{\{-?\s*("
            + "|".join(re.escape(n) for n in sorted(names))
            + r")\s*-?\}\}/"
        )

        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml", ".j2")
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/"):
                continue
            lines = content.splitlines()
            for index, line in enumerate(lines):
                match = pattern.search(line)
                if not match:
                    continue
                if is_suppressed_at(lines, index + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, index + 1, match.group(1)))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {v} already ends in a slash"
                for p, n, v in sorted(findings)
            )
            self.fail(
                "A tls url.base value already carries its trailing slash, so "
                "appending one produces a double slash. Consumers that do not "
                "normalise then build URLs like https://host//healthcheck, "
                "which a swarm vhost forwards verbatim.\n\n"
                "Default: drop the appended slash.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
