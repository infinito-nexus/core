"""Unit tests for plugins/lookup/gpu.py.

Mocks the Ansible-side machinery (loader, lookup_loader, templar) and pins
that the lookup answers True only when the declaration AND the host fact
agree. The declaration resolution itself belongs to resource_filter and is
covered by tests.unit.python.plugins.filter.test_resource_filter.
"""

from __future__ import annotations

import unittest
import unittest.mock as mock
from typing import ClassVar

from ansible.errors import AnsibleError

from plugins.lookup.gpu import LookupModule

APPLICATIONS: ClassVar[dict] = {
    "web-svc-libretranslate": {"services": {"libretranslate": {"gpu": True}}},
    "web-app-plain": {"services": {"plain": {"gpu": False}}},
    "web-app-stringy": {"services": {"stringy": {"gpu": "false"}}},
    "web-app-truthy": {"services": {"truthy": {"gpu": "yes"}}},
}

PRESENT: ClassVar[dict] = {"sys_svc_container_nvidia_device": {"stat": {"exists": True}}}
ABSENT: ClassVar[dict] = {"sys_svc_container_nvidia_device": {"stat": {"exists": False}}}


class _Templar:
    def __init__(self, vars_=None):
        self.available_variables = vars_ or {}

    def template(self, value, **_):
        return value


def _make_lookup(vars_=None):
    lm = LookupModule()
    lm._templar = _Templar(vars_ or {})
    lm._loader = mock.MagicMock()
    return lm


def _run(lm, terms):
    loaded = mock.MagicMock()
    loaded.run.return_value = [APPLICATIONS]
    with mock.patch("plugins.lookup.gpu.lookup_loader") as loader:
        loader.get.return_value = loaded
        return lm.run(terms, variables=lm._templar.available_variables)


class TestGpuLookup(unittest.TestCase):
    def test_declared_and_device_present_is_true(self):
        lm = _make_lookup(PRESENT)
        self.assertEqual(_run(lm, ["web-svc-libretranslate", "libretranslate"]), [True])

    def test_declared_without_a_device_is_false(self):
        """The case that selected a -cuda tag with no manifest for the platform."""
        lm = _make_lookup(ABSENT)
        self.assertEqual(_run(lm, ["web-svc-libretranslate", "libretranslate"]), [False])

    def test_undeclared_with_a_device_is_false(self):
        lm = _make_lookup(PRESENT)
        self.assertEqual(_run(lm, ["web-app-plain", "plain"]), [False])

    def test_missing_register_is_false(self):
        """Before sys-svc-container runs the register is absent, not falsy."""
        lm = _make_lookup({})
        self.assertEqual(_run(lm, ["web-svc-libretranslate", "libretranslate"]), [False])

    def test_non_mapping_register_is_false(self):
        lm = _make_lookup({"sys_svc_container_nvidia_device": "skipped"})
        self.assertEqual(_run(lm, ["web-svc-libretranslate", "libretranslate"]), [False])

    def test_a_false_string_declaration_is_false(self):
        """Jinja's `| bool` reads "false" as False where bool() reads it as True.

        The call sites this lookup replaces used `| bool`, so answering True
        here would attach a GPU runtime nothing asked for.
        """
        lm = _make_lookup(PRESENT)
        self.assertEqual(_run(lm, ["web-app-stringy", "stringy"]), [False])

    def test_a_yes_string_declaration_is_true(self):
        lm = _make_lookup(PRESENT)
        self.assertEqual(_run(lm, ["web-app-truthy", "truthy"]), [True])

    def test_rejects_no_terms(self):
        lm = _make_lookup(PRESENT)
        with self.assertRaises(AnsibleError):
            _run(lm, [])

    def test_rejects_three_terms(self):
        lm = _make_lookup(PRESENT)
        with self.assertRaises(AnsibleError):
            _run(lm, ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
