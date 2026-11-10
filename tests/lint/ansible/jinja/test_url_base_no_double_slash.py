from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "url-base-double-slash"
_ADDON_RULE = "url-base-addon-value"
_STRIP_RULE = "url-base-strip"

_SCAN_PREFIXES = ("roles/", "group_vars/")
_ADDON_DIRS = ("/meta/addons/", "/tasks/addons/")
_INSTANCE_KEYS = ("oauth_instance_url", "openproject_instance_url", "url")
_CONFIGKEY = re.compile(r"""configkey:\s*['"]?(?P<name>[A-Za-z0-9_.]+)""")
_URL_BASE = r"""lookup\(\s*['"]tls['"]\s*,[^)]*['"]url\.base['"]\s*\)"""
_DIRECT = re.compile(_URL_BASE + r"""\s*(?:\}\}/|~\s*['"]/)""")
_STRIP = (
    r"""(?:\s*\))*\s*(?:\|\s*(?:regex_replace\(\s*['"]/\+?\$['"]|trim\(\s*['"]/['"])"""
    r"""|\.rstrip\(\s*['"]/['"]\s*\))"""
)
_DIRECT_STRIP = re.compile(_URL_BASE + _STRIP)
_BARE_VAR = re.compile(
    r"""^\s*(?:-\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*['"]?\{\{\s*"""
    + _URL_BASE
    + r"""(?:\s*\|\s*trim)?\s*\}\}['"]?\s*$"""
)
_BARE_SET = re.compile(
    r"""\{%-?\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"""
    + _URL_BASE
    + r"""(?:\s*\|\s*trim)?\s*-?%\}"""
)


def _bare_url_base_names(files: list[tuple[str, list[str]]]) -> set[str]:
    """Return every variable name defined as a bare url.base lookup.

    Args:
      files: (relative path, lines) of every scanned file.

    Returns:
      names whose value is ``lookup('tls', ..., 'url.base')`` with at most a
      ``trim``, the value that always ends in "/".
    """
    names: set[str] = set()
    for _, lines in files:
        for line in lines:
            for pattern in (_BARE_VAR, _BARE_SET):
                match = pattern.search(line)
                if match:
                    names.add(match.group("name"))
    return names


def _double_slash_lines(lines: list[str], names: set[str]) -> list[int]:
    """Return the 1-based lines that append "/" to a url.base value.

    Args:
      lines: the file's lines.
      names: variables that hold a bare url.base.

    Returns:
      lines where url.base, directly or through one of ``names``, is followed
      by "}}/" or "~ '/".
    """
    via_name = (
        re.compile(
            r"""\{\{\s*(?:"""
            + "|".join(sorted(map(re.escape, names)))
            + r""")\s*(?:\}\}/|~\s*['"]/)"""
        )
        if names
        else None
    )
    return [
        index + 1
        for index, line in enumerate(lines)
        if _DIRECT.search(line) or (via_name and via_name.search(line))
    ]


def _strip_lines(lines: list[str], names: set[str]) -> list[int]:
    """Return the 1-based lines that strip the trailing "/" from url.base.

    Args:
      lines: the file's lines.
      names: variables that hold a bare url.base.

    Returns:
      lines where url.base, directly or through one of ``names``, goes through
      ``regex_replace('/$', '')``, ``regex_replace('/+$', '')``, ``trim('/')``
      or ``.rstrip('/')``.
    """
    via_name = (
        re.compile(
            r"""\b(?:""" + "|".join(sorted(map(re.escape, names))) + r""")\b""" + _STRIP
        )
        if names
        else None
    )
    return [
        index + 1
        for index, line in enumerate(lines)
        if _DIRECT_STRIP.search(line) or (via_name and via_name.search(line))
    ]


def _addon_bare_value_lines(lines: list[str], names: set[str]) -> list[int]:
    """Return the 1-based lines that hand an integration app a bare url.base.

    Args:
      lines: the addon file's lines.
      names: variables that hold a bare url.base.

    Returns:
      lines whose whole value is url.base or one of ``names`` and that are a
      ``configvalue`` of one of ``_INSTANCE_KEYS``, a ``url`` key, or a
      ``*_base_url`` fact.
    """
    pattern = re.compile(
        r"""^\s*(?:-\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*['"]?\{\{\s*(?:"""
        + _URL_BASE
        + (("|" + "|".join(sorted(map(re.escape, names)))) if names else "")
        + r""")(?:\s*\|\s*trim)?\s*\}\}['"]?\s*$"""
    )
    found: list[int] = []
    configkey = ""
    for index, line in enumerate(lines):
        key = _CONFIGKEY.search(line)
        if key:
            configkey = key.group("name")
        match = pattern.search(line)
        if not match:
            continue
        name = match.group("key")
        if (
            (name == "configvalue" and configkey in _INSTANCE_KEYS)
            or name == "url"
            or name.endswith("_base_url")
        ):
            found.append(index + 1)
    return found


def _scanned_files() -> list[tuple[str, list[str]]]:
    files: list[tuple[str, list[str]]] = []
    for path_str, content in iter_project_files_with_content(
        extensions=(".yml", ".yaml", ".j2"),
        exclude_tests=True,
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(_SCAN_PREFIXES):
            files.append((rel, content.splitlines()))
    return files


class TestUrlBaseNoDoubleSlash(unittest.TestCase):
    def test_addon_settings_hold_partner_urls_without_trailing_slash(self) -> None:
        files = _scanned_files()
        names = _bare_url_base_names(files)
        findings = [
            f"- {rel}:{line_no}: {lines[line_no - 1].strip()}"
            for rel, lines in files
            if any(part in rel for part in _ADDON_DIRS)
            for line_no in _addon_bare_value_lines(lines, names)
            if not is_suppressed_at(lines, line_no, _ADDON_RULE, mode="same-or-above")
        ]

        self.assertFalse(
            findings,
            "An addon setting holds lookup('tls', ..., 'url.base') as is, with "
            "its trailing '/'. Integration apps append their own paths to it "
            "(integration_openproject builds '<url>//oauth/token'), so store "
            "lookup('tls', ..., 'url.origin') instead. Mark a setting that needs "
            f"the slash with `# nocheck: {_ADDON_RULE}`.\n\nOffenders:\n"
            + "\n".join(findings),
        )

    def test_no_path_is_appended_to_url_base_with_a_leading_slash(self) -> None:
        files = _scanned_files()
        names = _bare_url_base_names(files)
        findings = [
            f"- {rel}:{line_no}: {lines[line_no - 1].strip()}"
            for rel, lines in files
            for line_no in _double_slash_lines(lines, names)
            if not is_suppressed_at(lines, line_no, _RULE, mode="same-or-above")
        ]

        self.assertFalse(
            findings,
            "lookup('tls', ..., 'url.base') ends in '/', so appending '/path' "
            "yields 'https://host//path', which exact-match OAuth redirect "
            "URIs and token endpoints reject. Append the path to "
            "lookup('tls', ..., 'url.origin'), join with `[base, 'path'] | "
            "url_join`, or append the path without its leading slash. Mark a "
            f"deliberate exception with `# nocheck: {_RULE}`.\n\nOffenders:\n"
            + "\n".join(findings),
        )

    def test_url_base_is_never_stripped_of_its_trailing_slash(self) -> None:
        files = _scanned_files()
        names = _bare_url_base_names(files)
        findings = [
            f"- {rel}:{line_no}: {lines[line_no - 1].strip()}"
            for rel, lines in files
            for line_no in _strip_lines(lines, names)
            if not is_suppressed_at(lines, line_no, _STRIP_RULE, mode="same-or-above")
        ]

        self.assertFalse(
            findings,
            "url.base is stripped of its trailing '/'. The tls lookup already "
            "returns that value as lookup('tls', ..., 'url.origin'), so read it "
            "there instead of rebuilding it per call site. Mark a deliberate "
            f"exception with `# nocheck: {_STRIP_RULE}`.\n\nOffenders:\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
