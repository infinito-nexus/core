"""Unit tests for the timeout lookup plugin.

Pins the scaling contract:

* factor unset -> identity (value-identical drop-in for the literal).
* TIMEOUT_FACTOR from play vars scales the base.
* an explicit ``factor=`` kwarg overrides the global.
* numeric strings are coerced; non-numeric / negative base or factor raises.
* exactly one positional term is required.
"""

from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_timeout", str(PROJECT_ROOT / "plugins/lookup/timeout.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod.LookupModule


class _DummyTemplar:
    def __init__(self, available_variables=None):
        self.available_variables = available_variables or {}

    def template(self, value):
        return value


class TestTimeoutLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.LookupModule = _load_lookup()

    def _make(self, variables):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar(variables)
        lm._loader = None
        return lm

    def test_factor_unset_is_identity(self):
        lm = self._make({})
        self.assertEqual(lm.run([3600], variables={}), [3600])

    def test_factor_one_is_identity(self):
        vars_ = {"TIMEOUT_FACTOR": 1}
        lm = self._make(vars_)
        self.assertEqual(lm.run([3600], variables=vars_), [3600])

    def test_factor_two_doubles(self):
        vars_ = {"TIMEOUT_FACTOR": 2}
        lm = self._make(vars_)
        self.assertEqual(lm.run([600], variables=vars_), [1200])

    def test_fractional_factor_rounds(self):
        vars_ = {"TIMEOUT_FACTOR": 1.5}
        lm = self._make(vars_)
        self.assertEqual(lm.run([100], variables=vars_), [150])

    def test_string_base_coerced(self):
        vars_ = {"TIMEOUT_FACTOR": 2}
        lm = self._make(vars_)
        self.assertEqual(lm.run(["300"], variables=vars_), [600])

    def test_string_factor_coerced(self):
        vars_ = {"TIMEOUT_FACTOR": "2"}
        lm = self._make(vars_)
        self.assertEqual(lm.run([300], variables=vars_), [600])

    def test_explicit_factor_kwarg_overrides_global(self):
        vars_ = {"TIMEOUT_FACTOR": 5}
        lm = self._make(vars_)
        self.assertEqual(lm.run([100], variables=vars_, factor=3), [300])

    def test_zero_base_stays_zero(self):
        vars_ = {"TIMEOUT_FACTOR": 4}
        lm = self._make(vars_)
        self.assertEqual(lm.run([0], variables=vars_), [0])

    def test_no_term_raises(self):
        lm = self._make({})
        with self.assertRaises(AnsibleError):
            lm.run([], variables={})

    def test_too_many_terms_raises(self):
        lm = self._make({})
        with self.assertRaises(AnsibleError):
            lm.run([1, 2], variables={})

    def test_non_numeric_base_raises(self):
        lm = self._make({})
        with self.assertRaises(AnsibleError):
            lm.run(["abc"], variables={})

    def test_negative_factor_raises(self):
        vars_ = {"TIMEOUT_FACTOR": -1}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run([100], variables=vars_)

    def test_none_terms_raises(self):
        lm = self._make({})
        with self.assertRaises(AnsibleError):
            lm.run(None, variables={})


if __name__ == "__main__":
    unittest.main(verbosity=2)
