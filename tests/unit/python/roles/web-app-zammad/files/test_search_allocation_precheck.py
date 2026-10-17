import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-zammad/files/shell/search_allocation_precheck.sh"

CURL_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${STUB_DIR}/calls"
case "$*" in
*_cluster/health*) exit "${HEALTH_RC}" ;;
*allocation/explain*) cat "${STUB_DIR}/explain" ;;
*"-X PUT"*) cat "${STUB_DIR}/created" ;;
esac
exit 0
"""

ALLOCATED = (
    '{"acknowledged":true,"shards_acknowledged":true,"index":"zammad_allocation_probe"}'
)
REFUSED = '{"acknowledged":true,"shards_acknowledged":false,"index":"zammad_allocation_probe"}'
WATERMARK = (
    '{"can_allocate":"no","node_allocation_decisions":[{"deciders":[{"decider":'
    '"disk_threshold","decision":"NO","explanation":"the node is above the high '
    "watermark cluster setting [cluster.routing.allocation.disk.watermark.high."
    'max_headroom=150gb]"}]}]}'
)


class TestSearchAllocationPrecheck(unittest.TestCase):
    def run_precheck(self, created, health_rc=0, entrypoint=("echo", "ENTRYPOINT")):
        """Run the precheck against a stubbed `curl` with a 1 s readiness deadline.

        Args:
            created: body the stubbed index creation answers with.
            health_rc: exit code of the stubbed `_cluster/health` probe.
            entrypoint: command the precheck execs once shards allocate.

        Returns:
            Tuple of the exit code, stdout plus stderr, and the recorded `curl` calls.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stub_dir = Path(tmp)
            curl = stub_dir / "curl"
            curl.write_text(CURL_STUB)
            curl.chmod(0o755)
            (stub_dir / "created").write_text(created)
            (stub_dir / "explain").write_text(WATERMARK)
            (stub_dir / "calls").write_text("")
            env = dict(os.environ)
            env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
            env["STUB_DIR"] = tmp
            env["HEALTH_RC"] = str(health_rc)
            env["ELASTICSEARCH_SCHEMA"] = "http"
            env["ELASTICSEARCH_HOST"] = "elasticsearch"
            env["ELASTICSEARCH_PORT"] = "9200"
            env["ELASTICSEARCH_NAMESPACE"] = "zammad"
            env["HOSTNAME"] = "0A1B2C3D4E5F"
            done = subprocess.run(
                ["bash", str(SCRIPT), "1", "1", "60", *entrypoint],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = (
                stub_dir / "calls"
            ).read_text()  # nocheck: cache-read tempdir fixture
            return done.returncode, done.stdout + done.stderr, calls

    def test_an_allocated_probe_starts_zammad_init(self):
        code, output, calls = self.run_precheck(ALLOCATED)
        self.assertEqual(code, 0)
        self.assertIn("ENTRYPOINT", output)
        self.assertIn(
            "-X PUT http://elasticsearch:9200/zammad_allocation_probe_0a1b2c3d4e5f?wait_for_active_shards=1&timeout=60s",
            calls,
        )
        self.assertEqual(calls.count("-X DELETE"), 2)

    def test_a_refused_shard_fails_with_the_watermark_explanation(self):
        code, output, calls = self.run_precheck(REFUSED)
        self.assertEqual(code, 1)
        self.assertNotIn("ENTRYPOINT", output)
        self.assertIn(
            "allocated no primary shard for zammad_allocation_probe_0a1b2c3d4e5f",
            output,
        )
        self.assertIn("watermark.high.max_headroom=150gb", output)
        self.assertIn("_cluster/allocation/explain", calls)
        self.assertEqual(calls.count("-X DELETE"), 2)

    def test_an_unreachable_search_service_fails_after_the_deadline(self):
        code, output, calls = self.run_precheck(ALLOCATED, health_rc=7)
        self.assertEqual(code, 1)
        self.assertIn("http://elasticsearch:9200 did not answer within 1s", output)
        self.assertNotIn("-X PUT", calls)

    def test_a_missing_entrypoint_is_refused(self):
        code, output, _ = self.run_precheck(ALLOCATED, entrypoint=())
        self.assertEqual(code, 2)
        self.assertIn("entrypoint required", output)


if __name__ == "__main__":
    unittest.main()
