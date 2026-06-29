#!/usr/bin/env python3
"""
Integration test: ensure every TOP-LEVEL ALL-CAPS variable is defined only once project-wide.

Scope (by design):
- group_vars/**/*.yml
- roles/*/vars/*.yml
- roles/*/defaults/*.yml
- roles/*/defauls/*.yml   # included on purpose in case of folder typos

A variable is considered a “constant” if its KEY (at the top level of a YAML document)
matches: ^[A-Z0-9_]+$

Only TOP-LEVEL keys are checked for uniqueness. Nested keys are ignored to allow
namespacing like DICTIONARYA.ENTRY and DICTIONARYB.ENTRY without conflicts.
"""

import glob
import os
import re
import unittest
from collections import defaultdict
from pathlib import Path

from utils.cache.yaml import load_yaml_all

UPPER_CONST_RE = re.compile(r"^[A-Z0-9_]+$")


def _iter_yaml_files():
    """Yield all YAML file paths in the intended scope."""
    patterns = [
        str(Path("group_vars") / "**" / "*.yml"),
        str(Path("roles") / "*" / "vars" / "*.yml"),
        str(Path("roles") / "*" / "defaults" / "*.yml"),
        str(Path("roles") / "*" / "defauls" / "*.yml"),  # intentionally included
    ]
    seen = set()
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):  # nocheck: project-walk
            norm = os.path.normpath(path)
            if norm not in seen and Path(norm).is_file():
                seen.add(norm)
                yield norm


def _extract_top_level_uppercase_keys(docs):
    """
    Return a set of TOP-LEVEL ALL-CAPS keys found across all mapping documents in a file.
    Nested keys are intentionally ignored.
    """
    found = set()
    for doc in docs:
        if isinstance(doc, dict):
            for k in doc:
                if isinstance(k, str) and UPPER_CONST_RE.match(k):
                    found.add(k)
    return found


class TestUppercaseConstantVarsUnique(unittest.TestCase):
    def test_uppercase_constants_unique(self):
        # Track where each TOP-LEVEL constant is defined
        constant_to_files = defaultdict(set)

        # Track YAML parse errors to fail with a helpful message
        parse_errors = []

        yaml_files = list(_iter_yaml_files())
        for yml in yaml_files:
            try:
                docs = list(load_yaml_all(yml))
            except Exception as e:
                parse_errors.append(f"{yml}: {e}")
                continue

            if not docs:
                continue

            file_constants = _extract_top_level_uppercase_keys(docs)

            for const in file_constants:
                constant_to_files[const].add(yml)

        if parse_errors:
            self.fail(
                "YAML parsing failed for one or more files:\n"
                + "\n".join(f"- {err}" for err in parse_errors)
            )

        # Duplicates are same TOP-LEVEL constant appearing in >1 files
        duplicates = {
            c: sorted(files) for c, files in constant_to_files.items() if len(files) > 1
        }

        if duplicates:
            msg_lines = [
                "Found TOP-LEVEL constants defined more than once. ",
                "ALL-CAPS top-level variables are treated as constants and must be defined only once project-wide.\n",
                "Nested ALL-CAPS keys are allowed and ignored by this test.",
                "",
            ]
            for const, files in sorted(duplicates.items()):
                msg_lines.append(f"* {const} defined in {len(files)} files:")
                msg_lines.extend(f"    - {f}" for f in files)
                msg_lines.append("")  # spacer
            self.fail("\n".join(msg_lines))


if __name__ == "__main__":
    unittest.main()
