import re
import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

SERVICES = PROJECT_ROOT / "roles" / "web-svc-seaweedfs" / ROLE_FILE_META_SERVICES
CONDITIONAL_WRITE_FIX = (4, 53)
RELEASE = re.compile(r"^(\d+)\.(\d+)$")


def _release(version):
    match = RELEASE.match(str(version))
    if match is None:
        raise AssertionError(
            f"the SeaweedFS pin {version!r} is no MAJOR.MINOR release, so its floor cannot be judged"
        )
    return tuple(int(part) for part in match.groups())


class TestSeaweedfsVersionPin(unittest.TestCase):
    def test_the_pin_carries_the_conditional_write_fix(self):
        version = load_yaml_any(str(SERVICES))["seaweedfs"]["version"]
        self.assertGreaterEqual(_release(version), CONDITIONAL_WRITE_FIX)

    def test_the_floor_check_refuses_the_release_with_the_bug(self):
        self.assertLess(_release("4.52"), CONDITIONAL_WRITE_FIX)
        self.assertGreaterEqual(_release("4.100"), CONDITIONAL_WRITE_FIX)

    def test_a_pin_that_is_no_release_is_refused(self):
        for version in ("latest", "4", "4.53-rc1"):
            with self.subTest(version=version), self.assertRaises(AssertionError):
                _release(version)


if __name__ == "__main__":
    unittest.main()
