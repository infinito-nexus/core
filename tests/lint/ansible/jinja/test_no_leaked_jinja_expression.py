"""Lint: Jinja expression syntax never appears outside a Jinja delimiter.

Inlining a ``{% set name = '<literal>' %}`` selector into the places that read
it is a common cleanup, and it is safe only while the right-hand side really is
one literal. Against a concatenation or a conditional, a regex that stops at
the first closing quote captures the *source text* of the expression instead of
its value, and writes it into the template body:

    {% set resting = ':where(' ~ scope ~ ')' %}   ->   :where(' ~ scope ~ ')
    {% set s = '.a' if x else '.b' %}             ->   .a' if x else '.b

Both render as literal text. In CSS that is a selector parse error, so the rule
is dropped and the page silently loses it; nothing downstream complains,
because the template is still valid Jinja and the stylesheet still parses as a
stylesheet with one rule fewer.

A template that genuinely needs ``if`` or ``~`` writes it inside ``{{ }}`` or
``{% %}``, which this lint strips before looking.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLES = PROJECT_ROOT / "roles"
DELIMITED = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
LEAKED = re.compile(r"'\s*~\s*\w|\w\s*~\s*'|'\s+if\s+.+\s+else\s+'")
RULE = "no-leaked-jinja-expression"


class TestNoLeakedJinjaExpression(unittest.TestCase):
    def test_no_template_carries_raw_expression_text(self) -> None:
        templates = sorted(ROLES.glob("*/**/*.j2"))
        self.assertTrue(templates, f"[{RULE}] no template found under {ROLES}")
        offenders = []
        for path in templates:
            body = DELIMITED.sub(
                lambda match: "\n" * match.group(0).count("\n"), read_text(str(path))
            )
            for number, line in enumerate(body.splitlines(), start=1):
                if LEAKED.search(line):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{number}: {line.strip()[:90]}"
                    )
        self.assertFalse(
            offenders,
            f"[{RULE}] Jinja expression text stands outside a delimiter and "
            "will render literally:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
