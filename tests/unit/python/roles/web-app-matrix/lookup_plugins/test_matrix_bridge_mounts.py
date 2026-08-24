"""Unit tests for the matrix_bridge_mounts lookup plugin."""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles/web-app-matrix/lookup_plugins/matrix_bridge_mounts.py"
    spec = importlib.util.spec_from_file_location("matrix_bridge_mounts", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables=None):
        self.available_variables = available_variables or {}

    def template(self, value):
        return value


class _FakeContainerLookup:
    def run(self, terms, variables=None, **kwargs):
        assert terms == ["web-app-matrix", "directories.instance"], terms
        return ["/opt/instances/matrix/"]


def _vars(**extra):
    base = {
        "application_id": "web-app-matrix",
        "MATRIX_BRIDGES": [{"bridge_name": "meta"}, {"bridge_name": "signal"}],
        "MATRIX_REGISTRATION_FILE_FOLDER": "/data/",
    }
    base.update(extra)
    return base


class TestMatrixBridgeMounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def _make(self, variables):
        lm = self.module.LookupModule()
        lm._templar = _DummyTemplar(variables)
        lm._loader = None
        return lm

    def _run(self, vars_):
        lm = self._make(vars_)
        with mock.patch.object(self.module, "lookup_loader") as loader_mock:
            loader_mock.get.return_value = _FakeContainerLookup()
            return lm.run([], variables=vars_)

    def test_one_mount_per_bridge(self):
        result = self._run(_vars())
        self.assertEqual(
            result,
            [
                [
                    "/opt/instances/matrix/mautrix/meta:/data/mautrix-meta:ro",
                    "/opt/instances/matrix/mautrix/signal:/data/mautrix-signal:ro",
                ]
            ],
        )

    def test_no_bridges_yields_empty_list(self):
        result = self._run(_vars(MATRIX_BRIDGES=[]))
        self.assertEqual(result, [[]])

    def test_terms_raise(self):
        lm = self._make(_vars())
        with self.assertRaises(AnsibleError):
            lm.run(["x"], variables=_vars())

    def test_missing_bridges_raises(self):
        vars_ = _vars()
        del vars_["MATRIX_BRIDGES"]
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run([], variables=vars_)

    def test_non_list_bridges_raises(self):
        lm = self._make(_vars(MATRIX_BRIDGES="meta"))
        with self.assertRaises(AnsibleError):
            lm.run([], variables=_vars(MATRIX_BRIDGES="meta"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
