import importlib.util
import sys
import unittest

from .atmo_bridge._fixtures import ENV, PYTHON_DIR, make_importable

SCRIPT = PYTHON_DIR / "bridge.py"


def _load():
    make_importable()
    spec = importlib.util.spec_from_file_location("atmo_bridge_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge = _load()


class TestMain(unittest.TestCase):
    def test_unknown_command_is_rejected(self):
        self.assertEqual(bridge.main(["bridge.py", "sync"], ENV), 2)


if __name__ == "__main__":
    unittest.main()
