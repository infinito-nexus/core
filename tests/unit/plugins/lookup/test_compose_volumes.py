"""Unit tests for the compose_volumes lookup plugin.

Pins the contract for the lookup that wraps the underlying
`compose_volumes` rendering function and auto-wires the `applications`
registry plus DEPLOYMENT_MODE and `storage` from the templating
context.
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from unittest import mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

_DIR_VAR_LIB = os.environ["INFINITO_DIR_VAR_LIB"]


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_compose_volumes",
        str(PROJECT_ROOT / "plugins/lookup/compose_volumes.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables=None):
        self.available_variables = available_variables or {}

    def template(self, value):
        return value


class TestComposeVolumesLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_lookup()
        cls.LookupModule = cls.module.LookupModule

    def _make(self, variables):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar(variables)
        lm._loader = None
        return lm

    def test_single_term_renders(self):
        vars_ = {"DEPLOYMENT_MODE": "compose", "DIR_VAR_LIB": _DIR_VAR_LIB}
        lm = self._make(vars_)
        with (
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
            mock.patch.object(
                self.module,
                "_render_compose_volumes",
                side_effect=lambda apps, app_id, **kw: (
                    f"called({app_id}, mode={kw.get('deployment_mode')})"
                ),
            ),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"web-app-x": {}}]
            )
            result = lm.run(["web-app-x"], variables=vars_)
        self.assertEqual(result, ["called(web-app-x, mode=compose)"])

    def test_deployment_mode_auto_wires_from_vars(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm", "DIR_VAR_LIB": _DIR_VAR_LIB}
        lm = self._make(vars_)
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        with (
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
            mock.patch.object(
                self.module, "_render_compose_volumes", side_effect=_render
            ),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"web-app-x": {}}]
            )
            lm.run(["web-app-x"], variables=vars_)
        self.assertEqual(captured.get("deployment_mode"), "swarm")

    def test_compose_mode_force_overrides_deployment_mode(self):
        vars_ = {
            "DEPLOYMENT_MODE": "swarm",
            "compose_mode_force": "compose",
            "DIR_VAR_LIB": _DIR_VAR_LIB,
        }
        lm = self._make(vars_)
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        with (
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
            mock.patch.object(
                self.module, "_render_compose_volumes", side_effect=_render
            ),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"web-app-x": {}}]
            )
            lm.run(["web-app-x"], variables=vars_)
        self.assertEqual(captured.get("deployment_mode"), "compose")

    def test_storage_auto_wires_from_vars(self):
        vars_ = {
            "DEPLOYMENT_MODE": "swarm",
            "DIR_VAR_LIB": _DIR_VAR_LIB,
            "storage": {"backend": "nfs", "nfs": {"server": "10.0.0.1"}},
        }
        lm = self._make(vars_)
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        with (
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
            mock.patch.object(
                self.module, "_render_compose_volumes", side_effect=_render
            ),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"web-app-x": {}}]
            )
            lm.run(["web-app-x"], variables=vars_)
        self.assertEqual(captured.get("storage"), vars_["storage"])

    def test_explicit_kwargs_override_auto_wired(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm", "DIR_VAR_LIB": _DIR_VAR_LIB}
        lm = self._make(vars_)
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        with (
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
            mock.patch.object(
                self.module, "_render_compose_volumes", side_effect=_render
            ),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"web-app-x": {}}]
            )
            lm.run(
                ["web-app-x"],
                variables=vars_,
                deployment_mode="compose",
                storage={"backend": "local"},
            )
        self.assertEqual(captured.get("deployment_mode"), "compose")
        self.assertEqual(captured.get("storage"), {"backend": "local"})

    def test_extra_volumes_kwarg_passes_through(self):
        vars_ = {"DEPLOYMENT_MODE": "compose", "DIR_VAR_LIB": _DIR_VAR_LIB}
        lm = self._make(vars_)
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        extra = {"data": {"name": "my-data"}}
        with (
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
            mock.patch.object(
                self.module, "_render_compose_volumes", side_effect=_render
            ),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"web-app-x": {}}]
            )
            lm.run(["web-app-x"], variables=vars_, extra_volumes=extra)
        self.assertEqual(captured.get("extra_volumes"), extra)

    def test_missing_deployment_mode_defaults_to_compose(self):
        vars_ = {"DIR_VAR_LIB": _DIR_VAR_LIB}
        lm = self._make(vars_)
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        with (
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
            mock.patch.object(
                self.module, "_render_compose_volumes", side_effect=_render
            ),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"web-app-x": {}}]
            )
            lm.run(["web-app-x"], variables=vars_)
        self.assertEqual(captured.get("deployment_mode"), "compose")

    def test_empty_terms_raises(self):
        lm = self._make({"DEPLOYMENT_MODE": "compose", "DIR_VAR_LIB": _DIR_VAR_LIB})
        with self.assertRaises(AnsibleError):
            lm.run([], variables={"DEPLOYMENT_MODE": "compose"})

    def test_none_terms_raises(self):
        lm = self._make({"DEPLOYMENT_MODE": "compose"})
        with self.assertRaises(AnsibleError):
            lm.run(None, variables={"DEPLOYMENT_MODE": "compose"})

    def test_too_many_terms_raises(self):
        lm = self._make({"DEPLOYMENT_MODE": "compose"})
        with self.assertRaises(AnsibleError):
            lm.run(["a", "b"], variables={"DEPLOYMENT_MODE": "compose"})

    def test_empty_application_id_raises(self):
        lm = self._make({"DEPLOYMENT_MODE": "compose"})
        with self.assertRaises(AnsibleError):
            lm.run([""], variables={"DEPLOYMENT_MODE": "compose"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
