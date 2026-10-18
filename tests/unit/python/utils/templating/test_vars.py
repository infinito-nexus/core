import unittest

from utils.templating.vars import resolve_var


class _Templar:
    def __init__(self, resolved=None, raises=False):
        self._resolved = resolved or {}
        self._raises = raises

    def template(self, value):
        if self._raises:
            raise RuntimeError("undefined variable")
        return self._resolved.get(value, value)


class TestResolveVar(unittest.TestCase):
    def test_a_template_is_resolved(self):
        templar = _Templar({"{{ stack_app }}": "web-app-docs"})
        self.assertEqual(resolve_var(templar, "{{ stack_app }}"), "web-app-docs")

    def test_a_plain_value_survives(self):
        self.assertEqual(resolve_var(_Templar(), "web-app-docs"), "web-app-docs")

    def test_without_a_templar_the_value_is_returned_as_is(self):
        self.assertEqual(resolve_var(None, "{{ stack_app }}"), "{{ stack_app }}")

    def test_none_is_returned_as_is(self):
        self.assertIsNone(resolve_var(_Templar(), None))

    def test_a_raising_templar_leaves_the_value_alone(self):
        """A lookup asks before the variable is necessarily defined, so a
        failure to render must not take the play down here."""
        self.assertEqual(
            resolve_var(_Templar(raises=True), "{{ stack_app }}"), "{{ stack_app }}"
        )

    def test_a_non_string_is_passed_through_the_templar(self):
        templar = _Templar()
        self.assertEqual(resolve_var(templar, {"a": 1}), {"a": 1})


if __name__ == "__main__":
    unittest.main()
