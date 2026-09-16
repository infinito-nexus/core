import re
import subprocess
import sys
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "sys-ctl-hlth-csp"
TASKS = ROLE / "tasks" / "00_core.yml"
SCRIPT = ROLE / "files" / "python" / "script.py"

_FLAG = re.compile(r"'\s*(--[a-z][a-z0-9-]*)")
_VALUE = {
    "--nginx-config-dir": "/nonexistent",
    "--image": "img",
    "--tor-proxy": "socks5://127.0.0.1:9050",
    "--onion-timeout": "1000",
}
_LIST_VALUE = {
    "--ignore-network-blocks-from": "a.test",
    "--skip-domain": "a.test",
    "--accept-status": "a.test=403",
}


def _flags_the_unit_passes() -> set[str]:
    return set(_FLAG.findall(read_text(str(TASKS))))


def _invoke(flag: str) -> subprocess.CompletedProcess:
    argv = [
        sys.executable,
        str(SCRIPT),
        "--nginx-config-dir",
        "/nonexistent",
        "--image",
        "img",
    ]
    if flag in _LIST_VALUE:
        argv.extend([flag, _LIST_VALUE[flag]])
    elif flag in _VALUE and flag not in ("--nginx-config-dir", "--image"):
        argv.extend([flag, _VALUE[flag]])
    elif flag not in _VALUE:
        argv.append(flag)
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)


class TestUnitFlagsAreParsable(unittest.TestCase):
    def test_the_unit_passes_at_least_the_known_flags(self):
        found = _flags_the_unit_passes()

        self.assertIn("--accept-status", found)
        self.assertIn("--onion-timeout", found)

    def test_every_flag_the_unit_passes_is_accepted_by_the_script(self):
        for flag in sorted(_flags_the_unit_passes()):
            with self.subTest(flag=flag):
                completed = _invoke(flag)
                self.assertNotIn(
                    "unrecognized arguments",
                    completed.stderr,
                    f"the systemd unit passes {flag} but script.py rejects it, "
                    f"which fails the service with status=2/INVALIDARGUMENT",
                )

    def test_an_undeclared_flag_is_still_rejected(self):
        completed = _invoke("--definitely-not-a-flag")

        self.assertIn("unrecognized arguments", completed.stderr)


if __name__ == "__main__":
    unittest.main()
