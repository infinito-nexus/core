"""Unit tests for the compose_volumes lookup plugin.

Pins the contract for the lookup that wraps the `compose_volumes`
rendering function and auto-wires `application_id`, the `applications`
registry, DEPLOYMENT_MODE, and `storage` from the templating context.
"""

from __future__ import annotations

import importlib.util
import os
import unittest
import unittest.mock as mock

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


def _vars(**extra):
    base = {
        "application_id": "web-app-x",
        "DEPLOYMENT_MODE": "compose",
        "DIR_VAR_LIB": _DIR_VAR_LIB,
    }
    base.update(extra)
    return base


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

    def _run(self, vars_, render, **kwargs):
        lm = self._make(vars_)
        with (
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
            mock.patch.object(self.module, "compose_volumes", side_effect=render),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"web-app-x": {}}]
            )
            return lm.run([], variables=vars_, **kwargs)

    def test_application_id_auto_wires_from_vars(self):
        result = self._run(
            _vars(),
            lambda apps, app_id, **kw: (
                f"called({app_id}, mode={kw.get('deployment_mode')})"
            ),
        )
        self.assertEqual(result, ["called(web-app-x, mode=compose)"])

    def test_deployment_mode_auto_wires_from_vars(self):
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        self._run(_vars(DEPLOYMENT_MODE="swarm"), _render)
        self.assertEqual(captured.get("deployment_mode"), "swarm")

    def test_compose_mode_force_overrides_deployment_mode(self):
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        self._run(_vars(DEPLOYMENT_MODE="swarm", compose_mode_force="compose"), _render)
        self.assertEqual(captured.get("deployment_mode"), "compose")

    def test_storage_auto_wires_from_vars(self):
        captured = {}
        storage = {"backend": "nfs", "nfs": {"server": "10.0.0.1"}}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        self._run(_vars(DEPLOYMENT_MODE="swarm", storage=storage), _render)
        self.assertEqual(captured.get("storage"), storage)

    def test_explicit_kwargs_override_auto_wired(self):
        captured = {}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        self._run(
            _vars(DEPLOYMENT_MODE="swarm"),
            _render,
            deployment_mode="compose",
            storage={"backend": "local"},
        )
        self.assertEqual(captured.get("deployment_mode"), "compose")
        self.assertEqual(captured.get("storage"), {"backend": "local"})

    def test_extra_volumes_kwarg_passes_through(self):
        captured = {}
        extra = {"data": {"name": "my-data"}}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        self._run(_vars(), _render, extra_volumes=extra)
        self.assertEqual(captured.get("extra_volumes"), extra)

    def test_missing_deployment_mode_defaults_to_compose(self):
        captured = {}
        vars_ = {"application_id": "web-app-x", "DIR_VAR_LIB": _DIR_VAR_LIB}

        def _render(apps, app_id, **kw):
            captured.update(kw)
            return ""

        self._run(vars_, _render)
        self.assertEqual(captured.get("deployment_mode"), "compose")

    def test_terms_raise(self):
        lm = self._make(_vars())
        with self.assertRaises(AnsibleError):
            lm.run(["web-app-x"], variables=_vars())

    def test_missing_application_id_raises(self):
        lm = self._make({"DEPLOYMENT_MODE": "compose", "DIR_VAR_LIB": _DIR_VAR_LIB})
        with self.assertRaises(AnsibleError):
            lm.run([], variables={"DEPLOYMENT_MODE": "compose"})

    def test_empty_application_id_raises(self):
        lm = self._make(_vars(application_id=""))
        with self.assertRaises(AnsibleError):
            lm.run([], variables=_vars(application_id=""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
