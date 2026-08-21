"""Unit tests for the nextcloud_extra_volumes lookup plugin."""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module():
    path = (
        PROJECT_ROOT
        / "roles/web-app-nextcloud/lookup_plugins/nextcloud_extra_volumes.py"
    )
    spec = importlib.util.spec_from_file_location("nextcloud_extra_volumes", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables=None):
        self.available_variables = available_variables or {}

    def template(self, value):
        return value


class _FakeVolumeLookup:
    def run(self, terms, variables=None, **kwargs):
        application_id, key = terms
        assert application_id == "web-app-nextcloud", terms
        return [{"name": f"nextcloud_{key}"}]


def _vars(**extra):
    base = {
        "application_id": "web-app-nextcloud",
        "NEXTCLOUD_WHITEBOARD_ENABLED": False,
        "NEXTCLOUD_RECORDING_ENABLED": False,
    }
    base.update(extra)
    return base


class TestNextcloudExtraVolumes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def _run(self, vars_):
        lm = self.module.LookupModule()
        lm._templar = _DummyTemplar(vars_)
        lm._loader = None
        with mock.patch.object(self.module, "lookup_loader") as loader_mock:
            loader_mock.get.return_value = _FakeVolumeLookup()
            return lm.run([], variables=vars_)

    def test_all_disabled_yields_empty_dict(self):
        self.assertEqual(self._run(_vars()), [{}])

    def test_whiteboard_adds_both_volumes(self):
        result = self._run(_vars(NEXTCLOUD_WHITEBOARD_ENABLED=True))
        self.assertEqual(
            result,
            [
                {
                    "whiteboard_tmp": {"name": "nextcloud_whiteboard_tmp"},
                    "whiteboard_fontcache": {"name": "nextcloud_whiteboard_fontcache"},
                }
            ],
        )

    def test_recording_adds_talk_volume(self):
        result = self._run(_vars(NEXTCLOUD_RECORDING_ENABLED=True))
        self.assertEqual(
            result,
            [{"talk_recording_tmp": {"name": "nextcloud_talk_recording_tmp"}}],
        )

    def test_terms_raise(self):
        lm = self.module.LookupModule()
        lm._templar = _DummyTemplar(_vars())
        lm._loader = None
        with self.assertRaises(AnsibleError):
            lm.run(["x"], variables=_vars())

    def test_missing_flag_raises(self):
        vars_ = _vars()
        del vars_["NEXTCLOUD_RECORDING_ENABLED"]
        lm = self.module.LookupModule()
        lm._templar = _DummyTemplar(vars_)
        lm._loader = None
        with mock.patch.object(self.module, "lookup_loader") as loader_mock:
            loader_mock.get.return_value = _FakeVolumeLookup()
            with self.assertRaises(AnsibleError):
                lm.run([], variables=vars_)


if __name__ == "__main__":
    unittest.main(verbosity=2)
