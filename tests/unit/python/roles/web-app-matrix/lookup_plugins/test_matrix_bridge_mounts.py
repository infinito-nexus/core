"""Unit tests for the matrix_bridge_mounts lookup plugin."""

from __future__ import annotations

import importlib.util
import unittest

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


def _vars(**extra):
    base = {
        "MATRIX_BRIDGES": [{"bridge_name": "meta"}, {"bridge_name": "signal"}],
        "MATRIX_BRIDGE_SOURCE_DIR": "/opt/instances/matrix/config/mautrix",
        "MATRIX_BRIDGE_CONFIG_TARGET": "/config/config.yaml",
        "MATRIX_REGISTRATION_FILE_FOLDER": "/registrations/",
    }
    base.update(extra)
    return base


class TestMatrixBridgeMounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def _run(self, terms, vars_=None):
        vars_ = _vars() if vars_ is None else vars_
        lm = self.module.LookupModule()
        lm._templar = _DummyTemplar(vars_)
        lm._loader = None
        return lm.run(terms, variables=vars_)

    def test_stack_declares_both_files_of_every_bridge(self):
        self.assertEqual(
            self._run(["stack"]),
            [
                {
                    "mautrix_meta_config": {
                        "file": "/opt/instances/matrix/config/mautrix/meta/config.yaml"
                    },
                    "mautrix_meta_registration": {
                        "file": "/opt/instances/matrix/config/mautrix/meta/registration.yaml"
                    },
                    "mautrix_signal_config": {
                        "file": "/opt/instances/matrix/config/mautrix/signal/config.yaml"
                    },
                    "mautrix_signal_registration": {
                        "file": "/opt/instances/matrix/config/mautrix/signal/registration.yaml"
                    },
                }
            ],
        )

    def test_synapse_mounts_one_registration_per_bridge(self):
        self.assertEqual(
            self._run(["synapse"]),
            [
                [
                    {
                        "source": "mautrix_meta_registration",
                        "target": "/registrations/mautrix-meta/registration.yaml",
                        "mode": 0o444,
                    },
                    {
                        "source": "mautrix_signal_registration",
                        "target": "/registrations/mautrix-signal/registration.yaml",
                        "mode": 0o444,
                    },
                ]
            ],
        )

    def test_bridge_mounts_only_its_own_config(self):
        self.assertEqual(
            self._run(["bridge", "signal"]),
            [
                [
                    {
                        "source": "mautrix_signal_config",
                        "target": "/config/config.yaml",
                        "mode": 0o444,
                    }
                ]
            ],
        )

    def test_no_bridges_declares_nothing(self):
        vars_ = _vars(MATRIX_BRIDGES=[])
        self.assertEqual(self._run(["stack"], vars_), [{}])
        self.assertEqual(self._run(["synapse"], vars_), [[]])

    def test_unknown_view_raises(self):
        for terms in ([], ["x"]):
            with self.assertRaises(AnsibleError):
                self._run(terms)

    def test_bridge_that_is_not_enabled_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["bridge", "whatsapp"])

    def test_missing_bridges_raises(self):
        vars_ = _vars()
        del vars_["MATRIX_BRIDGES"]
        with self.assertRaises(AnsibleError):
            self._run(["stack"], vars_)

    def test_non_list_bridges_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["stack"], _vars(MATRIX_BRIDGES="meta"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
