"""Lint: every script a role ships has a unit test at the mirrored path.

``roles/<role>/files/<lang>/<rel>`` is tested by
``tests/unit/<lang>/roles/<role>/files/<rel>``, renamed to that language's
framework convention. The language directory appears once - in ``tests/unit/``
- because ``tests/unit/python/`` already says what the file is.

::

    roles/web-app-keycloak/files/javascript/logout-panel.js
    tests/unit/javascript/roles/web-app-keycloak/files/logout-panel.test.js

    roles/svc-bkp-remote-2-local/files/python/pull_specific_host.py
    tests/unit/python/roles/svc-bkp-remote-2-local/files/test_pull_specific_host.py

Without a fixed mapping a shipped script is tested wherever its author
happened to look, and the next person cannot tell an untested file from one
whose test lives somewhere unexpected.

Exemption
---------

Most of what a role ships is a script against a live console - it connects to
a database, reads the container's environment, or calls ``exit`` on missing
input. There is no unit in it to test.

Such a file carries a ``nocheck: mirrored-unit-test`` comment stating why,
in whatever comment syntax its language uses::

    # nocheck: mirrored-unit-test - runs inside the Decidim console against
    # a live ActiveRecord connection; nothing here is callable in isolation

A file that has both a mirrored test and an exemption fails: the exemption
outlived its reason and reads as "untested" to everyone after you.

Find every exemption with::

    grep -rn 'nocheck: mirrored-unit-test' roles/
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLES = PROJECT_ROOT / "roles"
UNIT = PROJECT_ROOT / "tests" / "unit"
RULE = "mirrored-unit-test"
MIN_RATIONALE = 20

LANGUAGES = {
    "javascript": ".js",
    "php": ".php",
    "python": ".py",
    "ruby": ".rb",
}

_MARKER = re.compile(rf"nocheck:\s*{RULE}\b[ \t\-:]*(?P<why>.*)")


def _test_name(language: str, stem: str) -> str:
    """Return the test file name a language's framework discovers.

    :param language: directory name under ``files/`` and ``tests/unit/``
    :param stem: source file name without its suffix
    :return: the mirrored test's file name
    """
    if language == "python":
        return f"test_{stem.replace('-', '_')}.py"
    if language == "javascript":
        return f"{stem}.test.js"
    if language == "ruby":
        return f"{stem.replace('-', '_')}_test.rb"
    pascal = "".join(part.capitalize() for part in re.split(r"[_\-.]", stem) if part)
    return f"{pascal}Test.php"


def _shipped_scripts():
    """Yield ``(source, language, expected_test)`` for every governed script.

    :return: iterator over the role scripts this lint requires a test for
    """
    for language, suffix in sorted(LANGUAGES.items()):
        for source in sorted(ROLES.glob(f"*/files/{language}/**/*{suffix}")):
            if not source.is_file() or source.name == "__init__.py":
                continue
            parts = source.relative_to(ROLES).parts
            role, rel = parts[0], parts[3:]
            expected = UNIT.joinpath(
                language, "roles", role, "files", *rel[:-1]
            ) / _test_name(language, source.stem)
            yield source, language, expected


def _exemption(source):
    """Return the rationale of ``source``'s exemption, or ``None``.

    :param source: the shipped script to inspect
    :return: the text after the marker, or ``None`` when unexempted
    """
    match = _MARKER.search(read_text(str(source)))
    return match.group("why").strip() if match else None


class TestMirroredUnitTests(unittest.TestCase):
    def test_every_script_is_tested_or_exempt(self) -> None:
        missing = []
        for source, _, expected in _shipped_scripts():
            if expected.is_file() or _exemption(source) is not None:
                continue
            missing.append(
                f"{source.relative_to(PROJECT_ROOT)}\n    expected: "
                f"{expected.relative_to(PROJECT_ROOT)}"
            )

        self.assertFalse(
            missing,
            "these role scripts have neither a mirrored unit test nor a "
            f"'nocheck: {RULE} - <why>' comment:\n  " + "\n  ".join(missing),
        )

    def test_every_exemption_says_why(self) -> None:
        thin = []
        for source, _, _ in _shipped_scripts():
            why = _exemption(source)
            if why is not None and len(why) < MIN_RATIONALE:
                thin.append(str(source.relative_to(PROJECT_ROOT)))

        self.assertFalse(
            thin,
            "an exemption nobody can review is indistinguishable from an "
            "oversight; state what is untestable:\n  " + "\n  ".join(thin),
        )

    def test_no_exemption_sits_next_to_a_test(self) -> None:
        idle = []
        for source, _, expected in _shipped_scripts():
            if expected.is_file() and _exemption(source) is not None:
                idle.append(
                    f"{source.relative_to(PROJECT_ROOT)} is tested by "
                    f"{expected.relative_to(PROJECT_ROOT)}"
                )

        self.assertFalse(
            idle,
            f"drop the 'nocheck: {RULE}' comment, the test exists:\n  "
            + "\n  ".join(idle),
        )


if __name__ == "__main__":
    unittest.main()
