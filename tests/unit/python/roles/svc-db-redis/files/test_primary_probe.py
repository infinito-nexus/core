"""``primary_probe.sh`` of svc-db-redis.

Sentinel answers with the hostname a replica announced. When it answers with
an IP instead, the probe must map it to the instance whose swarm task holds
that IP, and must never cut an IP at its first dot into a bogus service key.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "svc-db-redis" / "files" / "shell" / "primary_probe.sh"
)
CONTAINER_STUB = """#!/usr/bin/env bash
[ "$1" = exec ] || exit 0
if [ "$3" = getent ]; then
	[ "$5" = "tasks.redis_redis-m2" ] && printf '%s tasks.redis_redis-m2\\n' "${M2_IP}"
	exit 0
fi
printf '%s\\n%s\\n' "${SENTINEL_ANSWER}" 6379
"""
RESOLVER_STUB = """#!/usr/bin/env bash
echo "$2" >> "${RESOLVE_LOG}"
printf 'cid-%s\\n' "$2"
"""


class TestRedisPrimaryProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy(SCRIPT, self.tmp / "primary-probe-redis")
        for name, body in (
            ("resolve-container-id", RESOLVER_STUB),
            ("container", CONTAINER_STUB),
        ):
            path = self.tmp / name
            path.write_text(body)
            path.chmod(0o755)
        self.log = self.tmp / "resolve.log"

    def _run(self, answer, instance):
        env = {
            **os.environ,
            "PATH": f"{self.tmp}:{os.environ['PATH']}",
            "SENTINEL_ANSWER": answer,
            "M2_IP": "10.0.1.7",
            "RESOLVE_LOG": str(self.log),
        }
        return subprocess.run(
            ["bash", str(self.tmp / "primary-probe-redis"), "redis", instance],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        ).returncode

    def test_asks_the_sentinel_on_the_instance_host(self):
        self._run("redis-m1", "redis-m1")
        log = self.log.read_text()  # nocheck: cache-read  the stub appends to this log during the test, a cached read would go stale
        self.assertEqual(log.split(), ["redis-sentinel-m1"])

    def test_hostname_answer_confirms_the_named_instance(self):
        self.assertEqual(self._run("redis-m1", "redis-m1"), 0)
        self.assertEqual(self._run("redis-m1", "redis-m2"), 1)

    def test_ip_answer_maps_to_the_instance_holding_it(self):
        self.assertEqual(self._run("10.0.1.7", "redis-m2"), 0)
        self.assertEqual(self._run("10.0.1.7", "redis-m1"), 1)

    def test_unknown_ip_confirms_no_instance(self):
        self.assertEqual(self._run("10.0.9.9", "redis-m2"), 1)

    def test_no_or_ipv6_answer_is_unknown(self):
        self.assertEqual(self._run("", "redis-m1"), 2)
        self.assertEqual(self._run("fe80::1", "redis-m1"), 2)

    def test_missing_args(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "redis"], capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 64)


if __name__ == "__main__":
    unittest.main()
