from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

TEST_SH = PROJECT_ROOT / "roles" / "svc-net-tor" / "files" / "test" / "test.sh"
BOUNDED = "DataDirectory /data\nNumCPUs 1\n"
UNBOUNDED = "DataDirectory /data\n"
CONTAINER_STUB = """\
in_container=/opt/chutney/net/nodes
exec sh -c "${5//"${in_container}"/"${NODES_DIR}"}"
"""


def _stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(
    torrcs: dict[str, str], flavor: str = "chutney", unreadable: str = ""
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        nodes = root / "nodes"
        nodes.mkdir()
        for node, torrc in torrcs.items():
            (nodes / node).mkdir()
            (nodes / node / "torrc").write_text(torrc, encoding="utf-8")
        if unreadable:
            (nodes / unreadable / "torrc").mkdir(parents=True)
        shutil.copy(TEST_SH, root / "test.sh")
        _stub(root / "onion_ports.py", "exit 0")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        _stub(bin_dir / "curl", "printf 200")
        _stub(bin_dir / "container", CONTAINER_STUB)
        return subprocess.run(
            ["bash", str(root / "test.sh"), "example.onion"],
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "NODES_DIR": str(nodes),
                "TOR_SOCKS": "127.0.0.1:9050",
                "NGINX_SERVERS_DIR": str(root),
                "RETRIES": "1",
                "SLEEP_SECONDS": "0",
                "TOR_DNSMASQ_CONF": str(root / "tor-onion.conf"),
                "TOR_CONTAINER": "tor",
                "TOR_FLAVOR": flavor,
            },
            capture_output=True,
            text=True,
            check=False,
        )


def _verdict(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout.splitlines()[-1]


class TestChutneyWorkerCheck(unittest.TestCase):
    def test_nodes_that_all_carry_the_limit_pass(self) -> None:
        result = _run({"000a": BOUNDED, "001a": BOUNDED})
        self.assertEqual(_verdict(result), "[OK]   every chutney node runs one worker")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_node_without_the_limit_is_named_and_fails(self) -> None:
        result = _run({"000a": BOUNDED, "001a": UNBOUNDED})
        self.assertIn("start one worker per host core", _verdict(result))
        self.assertTrue(_verdict(result).endswith("/001a/torrc"), _verdict(result))
        self.assertNotIn("000a", _verdict(result))
        self.assertEqual(result.returncode, 1)

    def test_nodes_that_all_lack_the_limit_fail(self) -> None:
        result = _run({"000a": UNBOUNDED, "001a": UNBOUNDED})
        self.assertIn("/000a/torrc", _verdict(result))
        self.assertIn("/001a/torrc", _verdict(result))
        self.assertEqual(result.returncode, 1)

    def test_no_torrc_to_inspect_fails(self) -> None:
        result = _run({})
        self.assertEqual(
            _verdict(result), "[FAIL] cannot read the chutney node torrcs in tor"
        )
        self.assertEqual(result.returncode, 1)

    def test_a_torrc_that_cannot_be_read_fails_beside_bounded_nodes(self) -> None:
        result = _run({"000a": BOUNDED}, unreadable="001a")
        self.assertEqual(
            _verdict(result), "[FAIL] cannot read the chutney node torrcs in tor"
        )
        self.assertEqual(result.returncode, 1)

    def test_the_public_flavor_does_not_run_the_check(self) -> None:
        result = _run({}, flavor="public")
        self.assertEqual(_verdict(result), "[INFO] 1 probed, 0 failed")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
