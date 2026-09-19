"""No two entries of a ``meta/variants.yml`` may declare the same override.

A variant exists to deploy a shape the other entries do not. Two entries with
the same content produce the same rendered payload, so the matrix plans them as
separate rows, assigns each its own axes and spends a deploy job on each. The
measured cost of one such job in this repository's CI is around one hundred
minutes, and the second one proves nothing the first did not.

The duplicate is also invisible in the plan table, which lists rows by
``role#variant``: the two read as different rows and only their identical
``embeds`` and ``weight`` betray them.

Comparison is on the parsed payload, not the file text, so two entries that
differ in key order, indentation or comments still count as the same. ``null``
normalises to ``{}`` the way the loader treats it, because a bare ``- `` list
item and an explicit ``- {}`` declare the same no-override entry.

Per-file opt-out
================
``# nocheck: variants-duplicate`` anywhere in the file, with a reason naming
what the repetition buys. Reserve it for a role whose variants are told apart
by something outside the entry, and say what that is; the default path is to
delete the entry, because the axes a duplicate would have covered are assigned
per row rather than declared per variant.
"""

from __future__ import annotations

import json
import unittest
from collections import defaultdict

from utils.annotations.suppress import is_suppressed_anywhere
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

RULE = "variants-duplicate"


def _fingerprint(entry: object) -> str:
    """The entry's content, independent of key order and of ``null`` vs ``{}``."""
    return json.dumps(entry if entry is not None else {}, sort_keys=True, default=str)


class TestVariantsDistinct(unittest.TestCase):
    def test_no_two_variants_declare_the_same_override(self) -> None:
        offenders = []
        for variants_file in sorted(
            (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_VARIANTS}")
        ):
            entries = load_yaml_any(str(variants_file), default_if_missing=[])
            if not isinstance(entries, list):
                continue
            if is_suppressed_anywhere(read_text(str(variants_file)).splitlines(), RULE):
                continue

            seen: dict[str, list[int]] = defaultdict(list)
            for index, entry in enumerate(entries):
                seen[_fingerprint(entry)].append(index)

            role = variants_file.parent.parent.name
            for indices in seen.values():
                if len(indices) > 1:
                    joined = ", ".join(f"#{index}" for index in indices)
                    offenders.append(
                        f"{role}: variants {joined} declare the same override"
                    )

        self.assertEqual(
            [],
            offenders,
            "A duplicated variant entry costs a deploy job and proves nothing the "
            "entry it repeats did not. Delete the repetition, give it the override "
            f"that makes it a distinct shape, or mark the file `# nocheck: {RULE}` "
            "with a reason:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
