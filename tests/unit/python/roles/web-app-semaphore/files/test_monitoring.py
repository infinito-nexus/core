from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from .monitoring._fake_monitoring import (
    ID,
    LABEL,
    LOGIN,
    RELEASED,
    SHELL,
    FakeBao,
    FakeCheckmk,
    env,
    monitoring,
    planned_for,
    removed_plan,
)


class TestTheShellRefusals(unittest.TestCase):
    def shell(self, environment):
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run(
                ["bash", str(SHELL)],
                cwd=tmp,
                env={"PATH": os.environ["PATH"], "HOME": tmp, **environment},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(run.returncode, 2, run.stderr)
        return json.loads(run.stdout.splitlines()[-1])

    def test_a_refusal_inside_a_command_substitution_ends_on_the_refusal_line(
        self,
    ) -> None:
        self.assertEqual(
            self.shell(env()),
            {
                "workspace": ID,
                "refused": "the inventory repository holds no devices.yml",
            },
        )

    def test_a_missing_setting_refuses_with_the_refusal_line_before_any_write(
        self,
    ) -> None:
        for key in (
            "BAO_ADDR",
            "BAO_CACERT",
            "INFINITO_SRC_DIR",
            "DEPLOY_KNOWN_HOSTS",
            "SEMAPHORE_JWT",
        ):
            with self.subTest(key=key):
                environment = env()
                del environment[key]
                self.assertEqual(
                    self.shell(environment),
                    {"workspace": ID, "refused": f"{key} is unset"},
                )

    def test_an_inherited_undo_flag_refuses_before_any_write(self) -> None:
        for action in ("remove", "apply"):
            with self.subTest(action=action):
                self.assertEqual(
                    self.shell(
                        {**env(), "MONITOR_ACTION": action, "MONITOR_UNDO": "1"}
                    ),
                    {
                        "workspace": ID,
                        "refused": "MONITOR_UNDO is not taken by this action",
                    },
                )


class TestTheLastLine(unittest.TestCase):
    def test_the_last_line_reports_monitor_host(self) -> None:
        line = monitoring.result_line(
            planned_for(), True, {"changed": False, "kept": True}
        )
        self.assertEqual(
            line,
            json.dumps(
                {"workspace": ID, "host": "target", "checkmk": True, "prometheus": True}
            ),
        )

    def test_remove_reports_false(self) -> None:
        line = monitoring.result_line(
            removed_plan(),
            False,
            {"changed": True, "kept": False},
        )
        self.assertEqual(
            json.loads(line),
            {"workspace": ID, "host": "target", "checkmk": False, "prometheus": False},
        )


class TestThePreflight(unittest.TestCase):
    def preflight(self, bao, site, planned=None):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps(planned or planned_for()))
            login = Path(tmp) / "login.json"
            code = monitoring.main(
                ["preflight", str(plan), str(login)],
                env(),
                stdout=out,
                api=site,
                bao=(LookupError, bao),
            )
            held = None
            if login.exists():
                written = login.read_text()  # nocheck: cache-read tempdir file
                held = json.loads(written)
        return code, out.getvalue(), held

    def test_a_label_bound_to_another_host_refuses_before_any_write(self) -> None:
        bao = FakeBao({**LOGIN, LABEL: {"host": "other"}})
        site = FakeCheckmk()
        code, out, held = self.preflight(bao, site)
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(out)["refused"],
            "DNS_LABEL target is bound to host other, not to target",
        )
        self.assertEqual((bao.writes, site.calls, held), ([], [], None))

    def test_pending_changes_refuse_before_any_openbao_write(self) -> None:
        own = LOGIN["platform/monitoring/checkmk"]["username"]
        for pending, reason in (
            ("cmkadmin", "pending changes of another user"),
            (own, "pending changes of an earlier run"),
        ):
            with self.subTest(reason=reason):
                bao = FakeBao(LOGIN)
                site = FakeCheckmk()
                site.foreign = [pending]
                code, out, held = self.preflight(bao, site)
                self.assertEqual(code, 2)
                self.assertIn(reason, json.loads(out)["refused"])
                self.assertEqual((bao.writes, site.writes(), held), ([], [], None))

    def test_an_apply_on_a_released_host_refuses_at_the_preflight(self) -> None:
        bao = FakeBao({**LOGIN, RELEASED: {"proof": {}, "at": "earlier"}})
        site = FakeCheckmk()
        code, out, held = self.preflight(bao, site)
        self.assertEqual(code, 2)
        self.assertIn("was released in", json.loads(out)["refused"])
        self.assertEqual((bao.writes, site.calls, held), ([], [], None))

    def test_an_empty_tombstone_refuses_at_the_preflight_and_a_denied_read_fails(
        self,
    ) -> None:
        site = FakeCheckmk()
        code, out, held = self.preflight(FakeBao({**LOGIN, RELEASED: {}}), site)
        self.assertEqual(code, 2)
        self.assertIn("was released in", json.loads(out)["refused"])
        bao = FakeBao(LOGIN, failing={RELEASED: 403})
        code, out, held = self.preflight(bao, site)
        self.assertEqual((code, out, held, site.calls), (1, "", None, []))

    def test_negative_control_a_clean_site_hands_the_login_on(self) -> None:
        bao = FakeBao({**LOGIN, LABEL: {"host": "target"}})
        code, out, held = self.preflight(bao, FakeCheckmk())
        self.assertEqual((code, out, bao.writes), (0, "", []))
        self.assertEqual(held, {"checkmk": LOGIN["platform/monitoring/checkmk"]})

    def test_the_shell_runs_every_refusal_before_any_write(self) -> None:
        lines = read_text(str(SHELL)).splitlines()

        def first(command):
            return every(command)[0]

        def every(command):
            return [
                number
                for number, line in enumerate(lines)
                if f'monitoring.py" {command} ' in line
            ]

        undo_secrets, apply_secrets, remove_secrets = every("secrets")
        undo_checkmk, apply_checkmk, remove_checkmk = every("checkmk")
        self.assertLess(every("plan")[-1], first("preflight"))
        self.assertLess(
            first("preflight"),
            min(apply_secrets, apply_checkmk, remove_checkmk, remove_secrets),
        )
        self.assertLess(apply_secrets, apply_checkmk)
        self.assertLess(remove_checkmk, remove_secrets)
        self.assertLess(undo_secrets, undo_checkmk)

    def test_the_shell_settles_after_every_apply_write_and_undoes_a_claimed_host(
        self,
    ) -> None:
        text = read_text(str(SHELL))
        lines = text.splitlines()
        push = lines.index(
            'push_prometheus "${workdir}/prometheus-state.json" "${workdir}/prometheus"'
        )
        settle = next(
            number for number, line in enumerate(lines) if '.py" settle ' in line
        )
        result = next(
            number for number, line in enumerate(lines) if '.py" result ' in line
        )
        self.assertLess(push, settle)
        self.assertLess(settle, result)
        undo = text[
            text.index("undo_apply() {") : text.index(
                "\n}\n", text.index("undo_apply() {")
            )
        ]
        for step in (
            "export MONITOR_ACTION=remove",
            "MONITOR_UNDO=1",
            'monitoring.py" checkmk "${workdir}/undo.json"',
            'monitoring.py" secrets "${workdir}/undo.json"',
            'push_prometheus "${workdir}/undo-state.json"',
        ):
            with self.subTest(step=step):
                self.assertIn(step, undo)
        armed = lines.index("\tapplied=1")
        self.assertEqual(
            lines[armed + 1],
            '\tpython3 "${helpers}/monitoring.py" secrets "${workdir}/plan.json" "${workdir}/secrets.json"',
        )
        self.assertLess(settle, lines.index("\tapplied=0"))
        self.assertIn("trap 'finish $?' EXIT", lines)
        for signal, code in (("TERM", 143), ("HUP", 129), ("INT", 130)):
            with self.subTest(signal=signal):
                self.assertIn(f"trap 'interrupted {code}' {signal}", lines)
        finish = text[text.index("finish() {") :]
        self.assertLess(finish.index("trap '' TERM HUP INT"), finish.index("applied=0"))

    def finish(self, applied, fail="", end="false", signal_at=""):
        """Args:
        applied: whether the run holds apply writes no settle confirmed.
        fail: the ``monitoring.py`` command the stand-in fails, none if empty.
        end: the command the shell ends with.
        signal_at: the ``monitoring.py`` command during which the stand-in
            sends the shell a TERM, none if empty.

        Returns:
            The exit code, stderr and the steps run of a shell that defines
            ``undo_apply`` and ``finish`` of ``monitoring.sh`` and then fails.
        """
        text = read_text(str(SHELL))
        start = text.index("undo_apply() {")
        functions = text[start : text.index("\n}\n", text.index("finish() {")) + 3]
        traps = "\n".join(
            line for line in text.splitlines() if line.startswith("trap ")
        )
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "steps"
            script = (
                "set -euo pipefail\nexec 3>&1\n"
                "SCRIPT=monitoring.sh UNDO_FAILED=4 helpers=/x alias=ws-x MONITOR_HOST=target\n"
                f'workdir="{tmp}/work"\nmkdir "$workdir"\n'
                'python3() { local step="$2"; if [ "$1" = -I ]; then step="$3"; fi\n'
                '  echo "$step" >>"$RECORD"; if [ "$step" = "$SIGNAL_AT" ]; then kill -TERM $$; fi\n'
                '  [ "$step" != "$FAIL" ]; }\n'
                'push_prometheus() { echo push >>"$RECORD"; }\n'
                f"{functions}"
                f"applied={1 if applied else 0}\n"
                f"{traps}\n{end}\n"
            )
            done = subprocess.run(
                ["bash", "-c", script],
                env={
                    "PATH": os.environ["PATH"],
                    "RECORD": str(record),
                    "FAIL": fail,
                    "SIGNAL_AT": signal_at,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            steps = []
            if record.exists():
                written = record.read_text("utf-8")  # nocheck: cache-read tempdir
                steps = written.split()
        return done.returncode, done.stderr, steps

    def test_a_failure_after_the_apply_writes_takes_them_back(self) -> None:
        code, _, steps = self.finish(True)
        self.assertEqual(code, 1)
        self.assertEqual(steps, ["plan", "secrets", "prometheus", "push", "checkmk"])

    def test_a_failure_before_the_apply_writes_takes_nothing_back(self) -> None:
        self.assertEqual(self.finish(False), (1, "", []))

    def test_a_failing_undo_exits_4_and_names_what_is_left(self) -> None:
        code, stderr, steps = self.finish(True, fail="secrets")
        self.assertEqual(code, 4)
        self.assertIn("left its token, digest and agent key behind", stderr)
        self.assertIn("run monitoring remove for target", stderr)
        self.assertEqual(
            steps, ["plan", "secrets", "prometheus", "push", "checkmk", "refuse"]
        )
        code, stderr, steps = self.finish(True, fail="checkmk")
        self.assertEqual(code, 4)
        self.assertIn("left its Checkmk host behind", stderr)
        self.assertEqual(
            steps, ["plan", "secrets", "prometheus", "push", "checkmk", "refuse"]
        )

    def test_a_second_term_during_the_undo_never_cuts_it_short(self) -> None:
        for end in ("false", "kill -TERM $$"):
            with self.subTest(end=end):
                code, _, steps = self.finish(True, end=end, signal_at="secrets")
                self.assertEqual(code, 143 if "kill" in end else 1)
                self.assertEqual(
                    steps, ["plan", "secrets", "prometheus", "push", "checkmk"]
                )

    def test_a_signal_takes_the_apply_back_and_keeps_its_exit_status(self) -> None:
        for signal, status in (("TERM", 143), ("HUP", 129), ("INT", 130)):
            with self.subTest(signal=signal):
                code, _, steps = self.finish(True, end=f"kill -{signal} $$")
                self.assertEqual(code, status)
                self.assertEqual(
                    steps, ["plan", "secrets", "prometheus", "push", "checkmk"]
                )
                self.assertEqual(
                    self.finish(False, end=f"kill -{signal} $$")[::2], (status, [])
                )

    def test_a_signal_whose_undo_leaves_writes_exits_4(self) -> None:
        for signal in ("TERM", "HUP", "INT"):
            with self.subTest(signal=signal):
                code, stderr, steps = self.finish(
                    True, fail="checkmk", end=f"kill -{signal} $$"
                )
                self.assertEqual(code, 4)
                self.assertIn("left its Checkmk host behind", stderr)
                self.assertEqual(steps[-1], "refuse")

    def test_the_shell_fails_on_a_failing_inventory_and_refuses_symlinks(self) -> None:
        text = read_text(str(SHELL))
        listing = text.index("--list-hosts")
        self.assertNotIn("|| true", text[listing : text.index("\n", listing)])
        self.assertLess(
            text.index("-type l -print -quit"), text.index("ansible-inventory")
        )


if __name__ == "__main__":
    unittest.main()
