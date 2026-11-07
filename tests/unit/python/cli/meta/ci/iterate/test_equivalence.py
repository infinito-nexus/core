from __future__ import annotations

import unittest

from cli.meta.ci.iterate.equivalence import (
    DEPLOY_READ_RULES,
    directives_changed,
    equivalent,
)
from utils.roles.mapping import ROLE_FILE_META_VARIANTS


class TestPython(unittest.TestCase):
    def test_comment_and_wrap_only(self) -> None:
        old = "def f(a, b):\n    return a+b\n"
        new = "def f(\n    a,\n    b,\n):  # adds\n    return a + b\n"
        self.assertTrue(equivalent("x.py", old, new))

    def test_quote_style_only(self) -> None:
        self.assertTrue(equivalent("x.py", "x = 'a'\n", 'x = "a"\n'))

    def test_changed_constant_is_real(self) -> None:
        self.assertFalse(equivalent("x.py", "x = 1\n", "x = 2\n"))

    def test_changed_docstring_is_real(self) -> None:
        self.assertFalse(
            equivalent("x.py", 'def f():\n    "a"\n', 'def f():\n    "b"\n')
        )

    def test_unparsable_side_is_real(self) -> None:
        self.assertFalse(equivalent("x.py", "x = 1\n", "x = (\n"))


class TestYaml(unittest.TestCase):
    def test_quoting_and_comments_only(self) -> None:
        old = "- name: a\n  debug: {msg: 'x'}\n"
        new = '# c\n- name: a\n  debug:\n    msg: "x"\n'
        self.assertTrue(equivalent("t.yml", old, new))

    def test_mapping_reorder_is_real(self) -> None:
        self.assertFalse(equivalent("t.yaml", "a: 1\nb: 2\n", "b: 2\na: 1\n"))

    def test_value_change_is_real(self) -> None:
        self.assertFalse(equivalent("t.yml", "a: 1\n", "a: 3\n"))

    def test_unreadable_tag_counts_as_real_even_if_only_spacing_moved(self) -> None:
        self.assertFalse(
            equivalent("t.yml", "a: !unsafe '{{ x }}'\n", "a:  !unsafe '{{ x }}'\n")
        )

    def test_identical_text_needs_no_parse(self) -> None:
        self.assertTrue(equivalent("t.yml", "a: !unsafe 'x'\n", "a: !unsafe 'x'\n"))


class TestScalarTypes(unittest.TestCase):
    SWAPS = (("1", "true"), ("0", "false"), ("1", "1.0"))

    def test_yaml_type_swap_is_real(self) -> None:
        for old, new in self.SWAPS:
            with self.subTest(old=old, new=new):
                self.assertFalse(equivalent("t.yml", f"x: {old}\n", f"x: {new}\n"))

    def test_yaml_key_type_swap_is_real(self) -> None:
        self.assertFalse(equivalent("t.yml", "1: a\n", "true: a\n"))

    def test_json_type_swap_is_real(self) -> None:
        self.assertFalse(equivalent("a.json", '{"x": 1}', '{"x": true}'))

    def test_negative_control_same_type_respelled_stays_equal(self) -> None:
        self.assertTrue(equivalent("t.yml", "x: 1.10\ny: yes\n", "x: 1.1\ny: true\n"))


class TestLineOneAndShippedFiles(unittest.TestCase):
    def test_shebang_change_is_real(self) -> None:
        old = "#!/usr/bin/env python3\nprint(1)\n"
        self.assertFalse(equivalent("x.py", old, old.replace("python3", "python2")))

    def test_negative_control_comment_below_line_one_stays_equal(self) -> None:
        old = "#!/usr/bin/env python3\nprint(1)\n"
        self.assertTrue(equivalent("x.py", old, old + "# trailing\n"))

    def test_yaml_a_role_ships_needs_identical_text(self) -> None:
        for path in ("roles/r/files/c.yml", "roles/r/templates/c.yml"):
            with self.subTest(path=path):
                self.assertFalse(equivalent(path, "x: on\n", "x: true\n"))

    def test_coding_cookie_on_line_two_is_real(self) -> None:
        old = "#!/usr/bin/env python3\nx = 'a'\n"
        new = "#!/usr/bin/env python3\n# -*- coding: latin-1 -*-\nx = 'a'\n"
        self.assertFalse(equivalent("utils/x.py", old, new))

    def test_want_json_marker_is_real(self) -> None:
        old = "import json\nprint(1)\n"
        new = "import json\n# WANT_JSON\nprint(1)\n"
        self.assertFalse(equivalent("library/x.py", old, new))

    def test_negative_control_yaml_ansible_reads_compares_loaded(self) -> None:
        self.assertTrue(equivalent("roles/r/vars/c.yml", "x: on\n", "x: true\n"))


class TestDirectives(unittest.TestCase):
    def test_added_nocheck_is_a_directive_change(self) -> None:
        self.assertTrue(
            directives_changed("a: 1\n", "a: 1 # nocheck: role-file-spot\n")
        )

    def test_negative_control_plain_comment_is_not(self) -> None:
        self.assertFalse(directives_changed("a: 1\n", "a: 1 # why\n"))

    def test_isort_and_pyright_are_directives(self) -> None:
        for comment in ("# isort: skip", "# pyright: ignore"):
            with self.subTest(comment=comment):
                self.assertTrue(directives_changed("x = 1\n", f"x = 1  {comment}\n"))


class TestReadComments(unittest.TestCase):
    PINNED = "- services:\n    # variant-pin: web-app-x#reciprocal\n    a: {}\n"
    PLAIN = "- services:\n    a: {}\n"
    VARIANTS = f"roles/r/{ROLE_FILE_META_VARIANTS}"

    def test_retargeted_pin_is_real(self) -> None:
        new = self.PINNED.replace("reciprocal", "0")
        self.assertFalse(equivalent(self.VARIANTS, self.PINNED, new))

    def test_added_and_removed_pin_are_real(self) -> None:
        for old, new in ((self.PLAIN, self.PINNED), (self.PINNED, self.PLAIN)):
            with self.subTest(old=old):
                self.assertFalse(equivalent(self.VARIANTS, old, new))

    def test_negative_control_plain_comment_stays_format_only(self) -> None:
        self.assertTrue(equivalent(self.VARIANTS, self.PLAIN, "# why\n" + self.PLAIN))

    def test_dropped_deploy_read_rule_is_real(self) -> None:
        for marker in (
            *(f"# nocheck: {rule} why" for rule in DEPLOY_READ_RULES),
            "# NOCHECK: url, inventory-variable why",
        ):
            with self.subTest(marker=marker):
                self.assertFalse(
                    equivalent(self.VARIANTS, f"{marker}\n{self.PLAIN}", self.PLAIN)
                )

    def test_negative_control_lint_only_rule_stays_format_only(self) -> None:
        for marker in (
            "# nocheck: info-media why",
            "# nocheck: inventory-open-subtree-x why",
        ):
            with self.subTest(marker=marker):
                self.assertTrue(
                    equivalent(self.VARIANTS, f"{marker}\n{self.PLAIN}", self.PLAIN)
                )

    def test_duplicate_key_json_a_role_ships_is_real(self) -> None:
        old, new = '{"a": 1, "a": 2}', '{"a": 2}'
        self.assertFalse(equivalent("roles/r/files/a.json", old, new))


class TestOtherKinds(unittest.TestCase):
    def test_json_whitespace_only(self) -> None:
        self.assertTrue(equivalent("a.json", '{"a": [1, 2]}', '{\n  "a": [1,2]\n}'))

    def test_template_whitespace_is_real(self) -> None:
        self.assertFalse(equivalent("a.j2", "x\n", "x \n"))

    def test_added_file_is_real(self) -> None:
        self.assertFalse(equivalent("x.py", None, "x = 1\n"))

    def test_deleted_file_is_real(self) -> None:
        self.assertFalse(equivalent("x.py", "x = 1\n", None))


if __name__ == "__main__":
    unittest.main()
