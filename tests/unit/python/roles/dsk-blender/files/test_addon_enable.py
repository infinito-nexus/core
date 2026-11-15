import importlib.util
import io
import sys
import types
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/dsk-blender/files/python/addon_enable.py"


class _Blender:
    """Stand-in for the bpy and addon_utils modules Blender provides.

    Args:
        enabled: modules the saved preferences carry at start.
        loadable: modules ``addon_utils.enable`` manages to register.
    """

    def __init__(self, enabled=(), loadable=()):
        self.addons = set(enabled)
        self.loadable = set(loadable)
        self.enable_calls = []
        self.saves = 0
        self.bpy = types.SimpleNamespace(
            context=types.SimpleNamespace(
                preferences=types.SimpleNamespace(addons=self.addons)
            ),
            ops=types.SimpleNamespace(
                wm=types.SimpleNamespace(save_userpref=self._save)
            ),
        )
        self.addon_utils = types.SimpleNamespace(enable=self._enable)

    def _save(self):
        self.saves += 1

    def _enable(self, module, default_set, persistent):
        self.enable_calls.append((module, default_set, persistent))
        if module in self.loadable:
            self.addons.add(module)

    def run(self, argv):
        modules = {"bpy": self.bpy, "addon_utils": self.addon_utils}
        spec = importlib.util.spec_from_file_location("__main__", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        out = io.StringIO()
        with (
            mock.patch.dict(sys.modules, modules),
            mock.patch.object(sys, "argv", argv),
            redirect_stdout(out),
        ):
            spec.loader.exec_module(module)
        return out.getvalue()


ARGV = ["blender", "--background", "--python-expr", "<source>", "--", "blender_mcp"]


class TestAddonEnable(unittest.TestCase):
    def test_absent_module_is_enabled_persistently(self):
        blender = _Blender(loadable={"blender_mcp"})
        blender.run(ARGV)
        self.assertEqual(blender.enable_calls, [("blender_mcp", True, True)])

    def test_absent_module_saves_the_preferences(self):
        blender = _Blender(loadable={"blender_mcp"})
        self.assertEqual(blender.run(ARGV).strip(), "ADDON=enabled")
        self.assertEqual(blender.saves, 1)

    def test_present_module_leaves_the_preferences_untouched(self):
        blender = _Blender(enabled={"blender_mcp"}, loadable={"blender_mcp"})
        self.assertEqual(blender.run(ARGV).strip(), "ADDON=present")
        self.assertEqual((blender.enable_calls, blender.saves), ([], 0))

    def test_refused_module_fails_without_saving(self):
        blender = _Blender()
        with self.assertRaises(RuntimeError):
            blender.run(ARGV)
        self.assertEqual(blender.saves, 0)

    def test_module_is_read_after_the_double_dash(self):
        blender = _Blender(loadable={"other_addon"})
        blender.run(["blender", "--background", "--", "other_addon"])
        self.assertIn("other_addon", blender.addons)


if __name__ == "__main__":
    unittest.main()
