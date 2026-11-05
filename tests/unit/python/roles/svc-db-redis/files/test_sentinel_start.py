"""Run the Redis Sentinel start-up wrapper against stub redis-cli/redis-server
binaries and check the Sentinel config it hands to redis-server."""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "svc-db-redis" / "files" / "shell" / "sentinel_start.sh"
)

FAKE_CLI = """#!/bin/sh
[ "$REDISCLI_AUTH" = "secret" ] || exit 1
while [ $# -gt 0 ]; do
  case "$1" in
    -h) host="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -f "$FAKE_DIR/answers/$host" ] || exit 1
cat "$FAKE_DIR/answers/$host"
"""

FAKE_SERVER = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_DIR/argv"
"""


def _read(path):
    return path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read  tempdir file the script under test rewrites


class SentinelStartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.base / "answers").mkdir()
        for name, body in (("redis-cli", FAKE_CLI), ("redis-server", FAKE_SERVER)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.password = self.base / "pw"
        self.password.write_text("secret\n", encoding="utf-8")
        self.conf = self.base / "sentinel.conf"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.bin}:{env['PATH']}",
                "FAKE_DIR": str(self.base),
                "SENTINEL_SELF": "redis-sentinel-a",
                "SENTINEL_PEERS": "redis-sentinel-b redis-sentinel-c",
                "SENTINEL_INSTANCES": "redis-a redis-b redis-c",
                "SENTINEL_MASTER_NAME": "redis",
                "SENTINEL_BOOTSTRAP": "redis-a",
                "SENTINEL_AUTH_USER": "sentinel",
                "SENTINEL_PASSWORD_FILE": str(self.password),
                "SENTINEL_CONF": str(self.conf),
                "SENTINEL_QUORUM": "2",
                "SENTINEL_DOWN_AFTER_MS": "5000",
                "SENTINEL_FAILOVER_MS": "10000",
                "SENTINEL_PARALLEL_SYNCS": "1",
                "SENTINEL_PORT": "26379",
                "REDIS_PORT": "6379",
                "SENTINEL_PEER_WAIT_S": "0",
            }
        )
        subprocess.run(["sh", str(SCRIPT)], env=env, check=True)
        argv = _read(self.base / "argv").split("\n")[:-1]
        self.assertEqual(argv, [str(self.conf), "--sentinel"])
        return _read(self.conf).splitlines()

    def test_fresh_sentinel_monitors_the_bootstrap_instance(self):
        lines = self._run()
        self.assertIn("sentinel monitor redis redis-a 6379 2", lines)
        for expected in (
            "sentinel resolve-hostnames yes",
            "sentinel announce-hostnames yes",
            "sentinel announce-ip redis-sentinel-a",
            "sentinel auth-user redis sentinel",
            "sentinel auth-pass redis secret",
            "requirepass secret",
            "sentinel down-after-milliseconds redis 5000",
            "sentinel failover-timeout redis 10000",
            "sentinel parallel-syncs redis 1",
        ):
            self.assertIn(expected, lines)

    def test_fresh_sentinel_follows_the_master_its_peers_report(self):
        (self.base / "answers" / "redis-sentinel-b").write_text(
            "redis-c\n6379\n", encoding="utf-8"
        )
        self.assertIn("sentinel monitor redis redis-c 6379 2", self._run())

    def test_rewritten_state_survives_and_owned_lines_are_refreshed(self):
        self.conf.write_text(
            "sentinel monitor redis redis-b 6379 3\n"
            "sentinel auth-pass redis old\n"
            "sentinel myid abc\n"
            "sentinel config-epoch redis 4\n"
            "sentinel known-replica redis redis-a 6379\n",
            encoding="utf-8",
        )
        lines = self._run()
        self.assertIn("sentinel monitor redis redis-b 6379 2", lines)
        self.assertIn("sentinel auth-pass redis secret", lines)
        self.assertNotIn("sentinel auth-pass redis old", lines)
        self.assertIn("sentinel myid abc", lines)
        self.assertIn("sentinel config-epoch redis 4", lines)
        self.assertIn("sentinel known-replica redis redis-a 6379", lines)
        self.assertLess(
            lines.index("sentinel monitor redis redis-b 6379 2"),
            lines.index("sentinel config-epoch redis 4"),
        )

    def test_restarted_sentinel_follows_its_peers_over_a_stale_saved_master(self):
        self.conf.write_text(
            "sentinel monitor redis redis-a 6379 2\n", encoding="utf-8"
        )
        for peer in ("redis-sentinel-b", "redis-sentinel-c"):
            (self.base / "answers" / peer).write_text(
                "redis-b\n6379\n", encoding="utf-8"
            )
        self.assertIn("sentinel monitor redis redis-b 6379 2", self._run())

    def test_peers_naming_an_unknown_instance_cast_no_vote(self):
        self.conf.write_text(
            "sentinel monitor redis redis-a 6379 2\n", encoding="utf-8"
        )
        (self.base / "answers" / "redis-sentinel-b").write_text(
            "redis-gone\n6379\n", encoding="utf-8"
        )
        self.assertIn("sentinel monitor redis redis-a 6379 2", self._run())


if __name__ == "__main__":
    unittest.main()
