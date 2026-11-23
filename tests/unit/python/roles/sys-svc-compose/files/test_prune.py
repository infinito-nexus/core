import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/sys-svc-compose"
SCRIPT = ROLE / "files/shell/prune.sh"

DEFAULTS = DataLoader().load_from_file(
    str(ROLE / "defaults/main.yml"), trusted_as_template=True
)
HANDLERS = DataLoader().load_from_file(
    str(ROLE / "handlers/main.yml"), trusted_as_template=True
)
PRUNE_HANDLER = next(h for h in HANDLERS if "ansible.builtin.script" in h)
RECORD_HANDLER = next(h for h in HANDLERS if "ansible.builtin.set_fact" in h)

CONTAINER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_CALLS"
if [ "$1" = "info" ]; then
\t[ -n "$STUB_ROOT" ] || exit 1
\tprintf '%s\\n' "$STUB_ROOT"
fi
exit 0
"""

DF_STUB = """#!/usr/bin/env bash
[ -n "$STUB_FREE_MIB" ] || exit 1
free="$STUB_FREE_MIB"
if [ -n "$STUB_FREE_AFTER_MIB" ] && grep -q 'image prune' "$STUB_CALLS"; then
\tfree="$STUB_FREE_AFTER_MIB"
fi
printf 'Avail\\n%sM\\n' "$free"
"""


def handler_env(last_free_mib):
    """
    Args:
        last_free_mib: compose_prune_last_free_mib when the prune handler runs.

    Returns:
        The environment the prune handler passes prune.sh under the role defaults.
    """
    variables = {**DEFAULTS, "compose_prune_last_free_mib": last_free_mib}
    rendered = Templar(loader=DataLoader(), variables=variables).template(
        PRUNE_HANDLER["environment"]
    )
    return {key: str(value) for key, value in rendered.items()}


class TestPruneScript(unittest.TestCase):
    def run_script(
        self, *, free_mib, free_after_mib="", root="/var/lib/docker", **overrides
    ):
        """
        Args:
            free_mib: free MiB ``df`` reports before a prune; empty fails the probe.
            free_after_mib: free MiB ``df`` reports once an image prune ran;
                empty keeps free_mib.
            root: the Docker data root ``container info`` reports; empty fails
                it. Omitted, Docker's stock root, since the ``df`` stub ignores
                the path and only its presence matters.
            overrides: PRUNE_* variables replacing the prune handler's
                environment under the role defaults; None leaves one unset.

        Returns:
            The completed process and the logged ``container`` calls.
        """
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            for name, body in (("container", CONTAINER_STUB), ("df", DF_STUB)):
                stub = bin_dir / name
                stub.write_text(body)
                stub.chmod(0o755)
            calls = Path(tmp) / "calls"
            calls.touch()
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "STUB_CALLS": str(calls),
                "STUB_ROOT": root,
                "STUB_FREE_MIB": free_mib,
                "STUB_FREE_AFTER_MIB": free_after_mib,
                **handler_env(""),
            }
            for key, value in overrides.items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = value
            proc = subprocess.run(
                ["bash", str(SCRIPT)],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )
            logged = calls.read_text()  # nocheck: cache-read stub log written per run
            return proc, logged.splitlines()

    def prunes(self, calls):
        return [call for call in calls if call.endswith(("prune -f", "prune -af"))]

    def flush(self, *, free_mib, free_after_mib, last_free_mib):
        """
        Args:
            free_mib: free MiB on the data root when the flush starts.
            free_after_mib: free MiB the prune leaves, if it runs.
            last_free_mib: compose_prune_last_free_mib before the flush.

        Returns:
            Whether the prune ran, and compose_prune_last_free_mib after the flush.
        """
        variables = {
            **DEFAULTS,
            "STORAGE_CONSTRAINED": True,
            "compose_prune_last_free_mib": last_free_mib,
        }
        proc, calls = self.run_script(
            free_mib=free_mib,
            free_after_mib=free_after_mib,
            **handler_env(last_free_mib),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = {"stdout": proc.stdout}
        templar = Templar(
            loader=DataLoader(),
            variables={**variables, "compose_prune_result": result},
        )
        result["changed"] = templar.evaluate_conditional(PRUNE_HANDLER["changed_when"])
        self.assertEqual(result["changed"], bool(self.prunes(calls)))
        templar = Templar(
            loader=DataLoader(),
            variables={**variables, "compose_prune_result": result},
        )
        if all(templar.evaluate_conditional(cond) for cond in RECORD_HANDLER["when"]):
            last_free_mib = str(
                templar.template(
                    RECORD_HANDLER["ansible.builtin.set_fact"][
                        "compose_prune_last_free_mib"
                    ]
                )
            )
        return result["changed"], last_free_mib

    def test_record_handler_follows_the_prune_on_its_topics(self):
        self.assertLess(HANDLERS.index(PRUNE_HANDLER), HANDLERS.index(RECORD_HANDLER))
        self.assertEqual(RECORD_HANDLER["listen"], PRUNE_HANDLER["listen"])

    def test_free_at_the_floor_skips_every_prune(self):
        proc, calls = self.run_script(free_mib="30720")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("prune skipped", proc.stdout)
        self.assertEqual(self.prunes(calls), [])

    def test_free_below_the_floor_prunes(self):
        proc, calls = self.run_script(free_mib="30719")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("prune skipped", proc.stdout)
        self.assertEqual(
            self.prunes(calls),
            [
                "container prune -f",
                "image prune -af",
                "volume prune -f",
                "buildx prune -af",
                "builder prune -af",
            ],
        )

    def test_unreadable_data_root_prunes(self):
        proc, calls = self.run_script(free_mib="999999", root="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.prunes(calls)), 5)

    def test_unmeasured_free_space_prunes(self):
        proc, calls = self.run_script(free_mib="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.prunes(calls)), 5)

    def test_missing_floor_fails_before_any_prune(self):
        proc, calls = self.run_script(free_mib="999999", PRUNE_FREE_FLOOR_MIB=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PRUNE_FREE_FLOOR_MIB", proc.stderr)
        self.assertEqual(self.prunes(calls), [])

    def test_missing_repeat_share_fails_before_any_prune(self):
        proc, calls = self.run_script(free_mib="1000", PRUNE_REPEAT_BELOW_PERCENT=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PRUNE_REPEAT_BELOW_PERCENT", proc.stderr)
        self.assertEqual(self.prunes(calls), [])

    def test_unset_last_free_space_fails_before_any_prune(self):
        proc, calls = self.run_script(free_mib="1000", PRUNE_LAST_FREE_MIB=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PRUNE_LAST_FREE_MIB", proc.stderr)
        self.assertEqual(self.prunes(calls), [])

    def test_worker_above_half_of_what_the_last_prune_kept_skips(self):
        proc, calls = self.run_script(free_mib="12001", PRUNE_LAST_FREE_MIB="24000")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("prune skipped", proc.stdout)
        self.assertEqual(self.prunes(calls), [])

    def test_worker_at_half_of_what_the_last_prune_kept_prunes(self):
        proc, calls = self.run_script(free_mib="12000", PRUNE_LAST_FREE_MIB="24000")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.prunes(calls)), 5)

    def test_record_below_half_the_floor_never_skips(self):
        for free_mib, last_free_mib in (("3", "0"), ("15000", "15359")):
            with self.subTest(last_free_mib=last_free_mib):
                proc, calls = self.run_script(
                    free_mib=free_mib, PRUNE_LAST_FREE_MIB=last_free_mib
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(len(self.prunes(calls)), 5)

    def test_record_at_half_the_floor_skips_above_half_of_it(self):
        proc, calls = self.run_script(free_mib="7681", PRUNE_LAST_FREE_MIB="15360")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("prune skipped", proc.stdout)
        self.assertEqual(self.prunes(calls), [])

    def test_record_does_not_skip_an_unmeasured_data_root(self):
        proc, calls = self.run_script(
            free_mib="999999", root="", PRUNE_LAST_FREE_MIB="24000"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.prunes(calls)), 5)

    def test_prune_below_the_floor_reports_what_it_kept(self):
        proc, calls = self.run_script(free_mib="20000", free_after_mib="21500")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.prunes(calls)), 5)
        self.assertIn("kept 21500 MiB free after the prune", proc.stdout)

    def test_prune_reaching_the_floor_reports_nothing_kept(self):
        proc, calls = self.run_script(free_mib="30000", free_after_mib="30720")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.prunes(calls)), 5)
        self.assertNotIn("kept", proc.stdout)

    def test_manager_run_prunes_once_per_halving_of_the_space_it_kept(self):
        flushes = [
            ("29000", "29500", True, "29500"),
            ("27000", "27500", False, "29500"),
            ("22000", "22500", False, "29500"),
            ("14751", "15000", False, "29500"),
            ("14750", "16000", True, "16000"),
            ("8001", "8500", False, "16000"),
            ("8000", "8500", True, "8500"),
            ("7000", "7500", True, "7500"),
        ]
        last_free_mib = ""
        for free_mib, free_after_mib, pruned, recorded in flushes:
            with self.subTest(free_mib=free_mib):
                ran, last_free_mib = self.flush(
                    free_mib=free_mib,
                    free_after_mib=free_after_mib,
                    last_free_mib=last_free_mib,
                )
                self.assertEqual(ran, pruned)
                self.assertEqual(last_free_mib, recorded)

    def test_host_whose_prune_regains_the_floor_prunes_below_it_every_flush(self):
        last_free_mib = ""
        for free_mib in ("30000", "29000", "30719"):
            with self.subTest(free_mib=free_mib):
                ran, last_free_mib = self.flush(
                    free_mib=free_mib,
                    free_after_mib="40000",
                    last_free_mib=last_free_mib,
                )
                self.assertTrue(ran)
                self.assertEqual(last_free_mib, "")


if __name__ == "__main__":
    unittest.main()
