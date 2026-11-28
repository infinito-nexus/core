from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from ._fake_monitoring import (
    COMMIT,
    ID,
    SETTINGS,
    SHELL_SETTINGS,
    WS,
    FakeBao,
    FakeCheckmk,
    env,
    monitoring,
    name_of,
    planned_for,
    survey,
)


class TestTheSurvey(unittest.TestCase):
    def _main(self, environment):
        out = io.StringIO()
        code = monitoring.main(["validate"], environment, stdout=out)
        return code, out.getvalue().strip().splitlines()

    def test_a_valid_survey_passes(self) -> None:
        for action, host in (
            ("apply", "target"),
            ("remove", "target"),
            ("apply", "192.0.2.10"),
            ("apply", "2001:db8::1"),
            ("apply", "2001:DB8::1"),
            ("remove", "Target"),
        ):
            with self.subTest(action=action, host=host):
                self.assertEqual(self._main(env(action, host)), (0, []))

    def test_every_spelling_of_a_host_names_one_checkmk_host(self) -> None:
        self.assertEqual(name_of("Target"), name_of("target"))
        self.assertEqual(name_of("2001:DB8:0::1"), name_of("2001:db8::1"))

    def test_an_ambiguous_legacy_ipv4_host_refuses(self) -> None:
        for host in ("01.2.3.4", "127.1", "0x7f000001"):
            with self.subTest(host=host):
                code, lines = self._main(env(host=host))
                self.assertEqual(code, 2)
                self.assertIn("ambiguous legacy IPv4", json.loads(lines[-1])["refused"])

    def test_every_other_value_refuses_with_the_refusal_line(self) -> None:
        for environment in (
            env(WORKSPACE=WS),
            env(WORKSPACE=ID.upper()),
            env(WORKSPACE=f"{ID}\n"),
            env("destroy"),
            env(""),
            env(host="bad host"),
            env(host="target\n"),
            env(host="-target"),
            env(host="fe80::1%a:b"),
            env(host="fe80::1%a_b"),
            env(WORKSPACE_PRIVATE_TARGETS="10.0.0.0/8"),
            env(WORKSPACE_PRIVATE_TARGETS='["not a network"]'),
            {key: value for key, value in env().items() if key != "MONITOR_HOST"},
        ):
            with self.subTest(env=environment):
                code, lines = self._main(environment)
                self.assertEqual(code, 2)
                last = json.loads(lines[-1])
                self.assertEqual(list(last), ["workspace", "refused"])
                self.assertTrue(last["refused"])

    def test_every_setting_is_required_and_named_when_missing(self) -> None:
        for key in (*SETTINGS, *SHELL_SETTINGS):
            with self.subTest(key=key):
                environment = env()
                del environment[key]
                code, lines = self._main(environment)
                self.assertEqual(code, 2)
                self.assertIn(key, json.loads(lines[-1])["refused"])

    def test_a_malformed_setting_refuses(self) -> None:
        for key, value in (
            ("MONITOR_CACERT", "relative.pem"),
            ("MONITOR_CHECKMK_API", "http://checkmk.example.org"),
            ("MONITOR_TLS_WARN_DAYS", "14"),
            ("MONITOR_TLS_CRIT_DAYS", "0"),
            ("MONITOR_PROMETHEUS_DIR", "instances"),
            ("MONITOR_PROMETHEUS_RELOAD_URL", "127.0.0.1:9090/-/reload"),
        ):
            with self.subTest(key=key):
                code, lines = self._main(env(**{key: value}))
                self.assertEqual(code, 2)
                self.assertIn(key, json.loads(lines[-1])["refused"])

    def test_apply_refuses_a_missing_or_malformed_commit_before_any_write(self) -> None:
        for value in (None, "", COMMIT.upper(), COMMIT[:39], f"{COMMIT}\n", "main"):
            with self.subTest(value=value):
                environment = env(INVENTORY_COMMIT=value)
                if value is None:
                    del environment["INVENTORY_COMMIT"]
                bao = FakeBao({})
                out = io.StringIO()
                with tempfile.TemporaryDirectory() as tmp:
                    code = monitoring.main(
                        [
                            "inventory-key",
                            str(Path(tmp) / "key"),
                            str(Path(tmp) / "zone"),
                        ],
                        environment,
                        stdout=out,
                        bao=(LookupError, bao),
                    )
                self.assertEqual(code, 2)
                self.assertIn("INVENTORY_COMMIT", json.loads(out.getvalue())["refused"])
                self.assertEqual((bao.reads, bao.writes), ([], []))

    def test_apply_refuses_a_missing_or_malformed_label_before_any_write(self) -> None:
        for value in (None, "", "Target", "-target", "a.b", "a" * 64, "target\n"):
            with self.subTest(value=value):
                environment = env(DNS_LABEL=value)
                if value is None:
                    del environment["DNS_LABEL"]
                bao = FakeBao({})
                out = io.StringIO()
                with tempfile.TemporaryDirectory() as tmp:
                    code = monitoring.main(
                        [
                            "inventory-key",
                            str(Path(tmp) / "key"),
                            str(Path(tmp) / "zone"),
                        ],
                        environment,
                        stdout=out,
                        bao=(LookupError, bao),
                    )
                self.assertEqual(code, 2)
                self.assertEqual(
                    json.loads(out.getvalue())["refused"],
                    "DNS_LABEL is no lowercase DNS label",
                )
                self.assertEqual((bao.reads, bao.writes), ([], []))

    def test_remove_takes_no_commit_and_no_label(self) -> None:
        self.assertEqual(self._main(env("remove")), (0, []))

    def test_remove_refuses_a_commit_or_a_label(self) -> None:
        for name, value in (("INVENTORY_COMMIT", COMMIT), ("DNS_LABEL", "target")):
            with self.subTest(name=name):
                code, lines = self._main(env("remove", **{name: value}))
                self.assertEqual(code, 2)
                self.assertEqual(
                    json.loads(lines[-1]),
                    {"workspace": ID, "refused": f"{name} is not taken by remove"},
                )

    def test_the_shell_refusal_ends_on_the_refusal_line(self) -> None:
        out = io.StringIO()
        code = monitoring.main(
            ["refuse", "INVENTORY_COMMIT x is not on main"], env(), stdout=out
        )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(out.getvalue()),
            {"workspace": ID, "refused": "INVENTORY_COMMIT x is not on main"},
        )

    def test_a_missing_inventory_read_key_refuses_without_a_traceback(self) -> None:
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "key"
            code = monitoring.main(
                ["inventory-key", str(key), str(Path(tmp) / "zone")],
                env(),
                stdout=out,
                bao=(LookupError, FakeBao({})),
            )
            self.assertFalse(key.exists())
        self.assertEqual(code, 2)
        self.assertIn(
            "no inventory read key of " + WS, json.loads(out.getvalue())["refused"]
        )

    def test_a_missing_dns_zone_refuses(self) -> None:
        bao = FakeBao(
            {f"platform/monitoring/inventory/{WS}": {"private_key": "PRIVATE"}}
        )
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "key"
            code = monitoring.main(
                ["inventory-key", str(key), str(Path(tmp) / "zone")],
                env(),
                stdout=out,
                bao=(LookupError, bao),
            )
            self.assertFalse(key.exists())
        self.assertEqual(code, 2)
        self.assertIn("no DNS zone of " + WS, json.loads(out.getvalue())["refused"])

    def test_the_held_inventory_read_key_and_zone_are_written(self) -> None:
        bao = FakeBao(
            {
                f"platform/monitoring/inventory/{WS}": {
                    "private_key": "PRIVATE",
                    "dns_zone": "ws.example.org",
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            key, zone = Path(tmp) / "key", Path(tmp) / "zone"
            code = monitoring.main(
                ["inventory-key", str(key), str(zone)],
                env(),
                stdout=io.StringIO(),
                bao=(LookupError, bao),
            )
            written_key = key.read_text("utf-8")  # nocheck: cache-read tempdir
            written_zone = zone.read_text("utf-8")  # nocheck: cache-read tempdir
        self.assertEqual(
            (code, written_key, written_zone), (0, "PRIVATE\n", "ws.example.org\n")
        )

    def test_the_refusal_line_keeps_the_decision_28_format(self) -> None:
        self.assertEqual(
            survey.refusal_line(WS, "why"),
            f'{{"workspace": "{WS}", "refused": "why"}}',
        )

    def test_a_refused_survey_writes_nothing(self) -> None:
        site = FakeCheckmk()
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps(planned_for()))
            (Path(tmp) / "secrets.json").write_text(
                json.dumps({"checkmk": {}, "token": None})
            )
            code = monitoring.main(
                [
                    "checkmk",
                    str(plan),
                    str(Path(tmp) / "secrets.json"),
                    str(Path(tmp) / "out.json"),
                ],
                env("rebuild"),
                stdout=io.StringIO(),
                api=site,
            )
        self.assertEqual(code, 2)
        self.assertEqual(site.calls, [])


if __name__ == "__main__":
    unittest.main()
