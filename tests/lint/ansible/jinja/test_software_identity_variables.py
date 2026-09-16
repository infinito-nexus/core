"""Lint: a template spells the software's identity through its variables.

``SOFTWARE_NAME``, ``SOFTWARE_DOMAIN``, ``SOFTWARE_URL`` and ``ORGANIZATION``
are declared once in ``group_vars/all/00_general.yml`` and derive from each
other. A template that writes the value instead of the variable forks that
single point: a rename reaches the four declarations and every consumer that
reads them, and silently misses the literal.

The check needs one literal only. ``SOFTWARE_DOMAIN`` is ``SOFTWARE_NAME |
lower``, ``SOFTWARE_URL`` is ``https://`` plus the domain and ``ORGANIZATION``
is the name again, so a case-insensitive search for the name's value finds the
value of all four. The value is read from the declaration rather than written
here, so renaming the software does not leave this lint hunting the old string.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: software-identity`` on the offending line or the one above it,
  for a literal that must survive a rename, such as an identifier a third
  party already issued under the old name.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "software-identity"
_SPOT = "group_vars/all/00_general.yml"
_NAME_KEY = "SOFTWARE_NAME"


def _software_name() -> str:
    """The literal value of ``SOFTWARE_NAME``, read from its declaration."""
    declared = load_yaml_any(str(PROJECT_ROOT / _SPOT))
    if not isinstance(declared, dict) or _NAME_KEY not in declared:
        raise AssertionError(f"{_SPOT} declares no {_NAME_KEY}")
    name = declared[_NAME_KEY]
    if not isinstance(name, str) or "{{" in name:
        raise AssertionError(
            f"{_SPOT}: {_NAME_KEY} is no longer a plain literal ({name!r}), so "
            "this lint can no longer derive what to search for"
        )
    return name


def _variable_for(line: str, start: int, matched: str) -> str:
    if line[:start].endswith(("https://", "http://")):
        return "SOFTWARE_URL"
    if matched.islower():
        return "SOFTWARE_DOMAIN"
    return f"{_NAME_KEY} (or ORGANIZATION)"


class TestSoftwareIdentityVariables(unittest.TestCase):
    def test_no_template_spells_out_the_software_identity(self) -> None:
        pattern = re.compile(re.escape(_software_name()), re.IGNORECASE)

        findings: list[str] = []
        for path in iter_project_files(extensions=(".j2",), exclude_tests=True):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(path).splitlines()
            for index, line in enumerate(lines):
                match = pattern.search(line)
                if match is None:
                    continue
                if is_suppressed_at(lines, index + 1, _RULE, mode="same-or-above"):
                    continue
                variable = _variable_for(line, match.start(), match.group(0))
                findings.append(
                    f"- {rel}:{index + 1}: {match.group(0)!r} -> {{{{ {variable} }}}}"
                )

        if findings:
            self.fail(
                "These templates write the software's identity as a literal, so a "
                f"rename in {_SPOT} would leave them behind:\n"
                + "\n".join(findings)
                + f"\n\nFix: render the declared variable instead. Mark it "
                f"`nocheck: {_RULE}` when the literal must survive a rename."
            )


if __name__ == "__main__":
    unittest.main()
