from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from pathlib import Path

from ._fake_monitoring import (
    AUTOMATION,
    HOST_KEY,
    ID,
    TLS_DAYS,
    WS,
    FakeCheckmk,
    RefusalError,
    RunError,
    apply,
    checkmk,
    env,
    monitoring,
    name_of,
    planned_for,
    target,
)


class TestForeignPendingChanges(unittest.TestCase):
    def test_a_foreign_pending_change_refuses_before_any_write(self) -> None:
        for action in ("apply", "remove"):
            with self.subTest(action=action):
                site = FakeCheckmk()
                if action == "remove":
                    apply(site)
                    site.calls.clear()
                site.foreign = ["cmkadmin"]
                activations = site.activations
                run = checkmk(site)
                with self.assertRaisesRegex(
                    RefusalError,
                    "checkmk has pending changes of another user",
                ):
                    if action == "apply":
                        run.apply(planned_for(), TLS_DAYS)
                    else:
                        run.remove(WS, "target")
                self.assertEqual(site.writes(), [])
                self.assertEqual(site.activations, activations)

    def test_the_refusal_ends_on_the_refusal_line(self) -> None:
        site = FakeCheckmk()
        site.foreign = ["cmkadmin"]
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps(planned_for()))
            secrets = Path(tmp) / "secrets.json"
            secrets.write_text(
                json.dumps({"checkmk": {"username": AUTOMATION}, "token": None})
            )
            code = monitoring.main(
                ["checkmk", str(plan), str(secrets), str(Path(tmp) / "out.json")],
                env(),
                stdout=out,
                api=site,
            )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(out.getvalue()),
            {
                "workspace": ID,
                "refused": "checkmk has pending changes of another user:"
                " cmkadmin: edit by cmkadmin",
            },
        )
        self.assertEqual(site.writes(), [])

    def test_own_stale_pending_changes_refuse_an_apply_before_any_write(self) -> None:
        site = FakeCheckmk()
        site.pending = 2
        with self.assertRaisesRegex(RefusalError, "pending changes of an earlier run"):
            checkmk(site).apply(planned_for(), TLS_DAYS)
        self.assertEqual(site.writes(), [])
        self.assertEqual(site.pending, 2)

    def test_a_remove_cleans_up_after_an_apply_that_died_before_activating(
        self,
    ) -> None:
        site = FakeCheckmk()
        apply(site)
        site.pending = 2
        self.assertFalse(checkmk(site).remove(WS, "target", own=True))
        self.assertNotIn(name_of("target"), site.hosts)
        self.assertEqual(site.pending, 0)

    def test_an_undo_activates_its_pending_deletion_after_the_folder_went(
        self,
    ) -> None:
        site = FakeCheckmk()
        apply(site)
        site.folders.clear()
        site.pending = 1
        site.calls.clear()
        with self.assertRaisesRegex(
            RefusalError,
            "pending changes of an earlier run: "
            f"{AUTOMATION}: edit by {AUTOMATION}: activate or revert",
        ):
            checkmk(site).remove(WS, "target")
        self.assertEqual((site.pending, site.writes()), (1, []))
        self.assertFalse(checkmk(site).remove(WS, "target", own=True))
        self.assertEqual(site.pending, 0)

    def test_a_remove_never_activates_changes_it_did_not_write(self) -> None:
        site = FakeCheckmk()
        apply(site)
        site.pending = 1
        site.calls.clear()
        activations = site.activations
        with self.assertRaisesRegex(RefusalError, "pending changes of an earlier run"):
            checkmk(site).remove(WS, "target")
        site.foreign = ["cmkadmin"]
        with self.assertRaisesRegex(RefusalError, "cmkadmin: edit by"):
            checkmk(site).remove(WS, "target", own=True)
        self.assertEqual((site.activations, site.writes()), (activations, []))

    def test_negative_control_no_pending_change_converges(self) -> None:
        site = FakeCheckmk()
        self.assertTrue(apply(site))
        self.assertEqual(site.pending, 0)


class TestTheCheckmkHost(unittest.TestCase):
    def test_folder_labels_and_name(self) -> None:
        site = FakeCheckmk()
        self.assertTrue(apply(site))
        attributes = site.hosts[name_of("target")]["attributes"]
        self.assertEqual(site.hosts[name_of("target")]["folder"], f"~workspaces~{WS}")
        self.assertEqual(
            attributes["labels"],
            {
                "workspace": WS,
                "instance": "target",
                "infinito/ssh_user": "deploy",
                "infinito/ssh_port": "22",
                "infinito/ssh_host_key_type": "ssh-ed25519",
                "infinito/ssh_host_key": HOST_KEY.split()[1],
            },
        )
        self.assertEqual(attributes["tag_agent"], "cmk-agent")

    def test_reachability_rules_carry_the_tls_levels(self) -> None:
        site = FakeCheckmk()
        apply(site)
        values = {
            rule["ruleset"]: ast.literal_eval(rule["extensions"]["value_raw"])
            for rule in site.rules.values()
        }
        self.assertEqual(values["active_checks:icmp"], {})
        http = values["active_checks:httpv2"]
        self.assertEqual(
            [endpoint["url"] for endpoint in http["endpoints"]],
            ["https://prometheus.target.example.org/", "https://target.example.org/"],
        )
        self.assertEqual(
            http["standard_settings"]["cert"],
            ("validate", ("fixed", (30 * 86400.0, 14 * 86400.0))),
        )

    def test_without_agent_no_ssh_labels_and_no_discovery(self) -> None:
        site = FakeCheckmk()
        apply(site, target=target({"agent": False}))
        attributes = site.hosts[name_of("target")]["attributes"]
        self.assertEqual(attributes["tag_agent"], "no-agent")
        self.assertEqual(set(attributes["labels"]), {"workspace", "instance"})
        self.assertEqual(site.discoveries(), [])

    def test_neither_kind_removes_only_that_host(self) -> None:
        site = FakeCheckmk()
        apply(site, "other", other=target(primary="other.example.org"))
        apply(site)
        held = apply(site, target=target({"reachability": False, "agent": False}))
        self.assertFalse(held)
        self.assertEqual(list(site.hosts), [name_of("other")])
        self.assertTrue(
            all(
                " other " in r["extensions"]["properties"]["description"]
                for r in site.rules.values()
            )
        )


class TestTheDiscovery(unittest.TestCase):
    def test_every_apply_of_an_agent_host_runs_fix_all(self) -> None:
        site = FakeCheckmk()
        apply(site)
        apply(site)
        self.assertEqual(
            site.discoveries(),
            [{"host_name": name_of("target"), "mode": "fix_all"}] * 2,
        )

    def test_a_failing_discovery_does_not_fail_the_run(self) -> None:
        site = FakeCheckmk()
        apply(site)
        calls = []

        def refusing(method, path, payload=None, headers=None):
            calls.append(path)
            if path.endswith("/service_discovery_run/actions/start/invoke"):
                return 400, {"detail": "agent unreachable"}
            return site(method, path, payload, headers)

        self.assertTrue(checkmk(refusing).apply(planned_for(), TLS_DAYS))

    def test_switching_the_agent_off_drops_the_services_it_gave(self) -> None:
        site = FakeCheckmk()
        apply(site)
        self.assertIn(name_of("target"), site.discovered)
        site.calls.clear()
        apply(site, target=target({"agent": False}))
        self.assertEqual(
            site.discoveries(), [{"host_name": name_of("target"), "mode": "fix_all"}]
        )
        self.assertNotIn(name_of("target"), site.discovered)
        self.assertEqual(site.pending, 0)

    def test_a_run_that_died_before_the_discovery_drops_the_services_next_time(
        self,
    ) -> None:
        site = FakeCheckmk()
        apply(site)
        site.hosts[name_of("target")]["attributes"]["tag_agent"] = "no-agent"
        apply(site, target=target({"agent": False}))
        self.assertNotIn(name_of("target"), site.discovered)

    def test_the_job_state_decides_and_a_lost_job_fails(self) -> None:
        site = FakeCheckmk()
        apply(site)
        site.discovery_state = "exception"
        with self.assertRaisesRegex(RunError, "ended exception"):
            apply(site, target=target({"agent": False}))
        site = FakeCheckmk()
        site.discovery_state = "exception"
        self.assertTrue(apply(site))

        def lost(method, path, payload=None, headers=None):
            if path.endswith("/actions/wait-for-completion/invoke"):
                return 404, {"title": "not found"}
            return site(method, path, payload, headers)

        with self.assertRaisesRegex(RunError, "waiting for the discovery"):
            checkmk(lost).apply(planned_for(), TLS_DAYS)

    def test_negative_control_a_refused_discovery_after_the_switch_fails(self) -> None:
        site = FakeCheckmk()
        apply(site)

        def refusing(method, path, payload=None, headers=None):
            if path.endswith("/service_discovery_run/actions/start/invoke"):
                return 400, {"detail": "refused"}
            return site(method, path, payload, headers)

        planned = planned_for(target=target({"agent": False}))
        with self.assertRaisesRegex(RunError, "the services its agent gave stay"):
            checkmk(refusing).apply(planned, TLS_DAYS)


class TestTheIdempotence(unittest.TestCase):
    def test_a_second_apply_writes_nothing_and_leaves_no_pending_change(self) -> None:
        site = FakeCheckmk()
        apply(site)
        self.assertEqual(site.pending, 0)
        site.calls.clear()
        activations = site.activations
        apply(site)
        self.assertEqual(site.writes(), [])
        self.assertEqual(site.pending, 0)
        self.assertEqual(site.activations, activations)

    def test_negative_control_a_changed_domain_rewrites_one_rule(self) -> None:
        site = FakeCheckmk()
        apply(site)
        site.calls.clear()
        apply(site, target=target(primary="other.example.org"))
        self.assertEqual([method for method, _ in site.writes()], ["PUT"])

    def test_apply_never_touches_another_host(self) -> None:
        site = FakeCheckmk()
        apply(site, "other", other=target(primary="other.example.org"))
        before = (dict(site.hosts), dict(site.rules))
        apply(site)
        self.assertIn(name_of("other"), site.hosts)
        self.assertEqual(site.hosts[name_of("other")], before[0][name_of("other")])
        self.assertTrue(set(before[1]) <= set(site.rules))

    def test_remove_drops_the_host_and_the_folder_once_empty(self) -> None:
        site = FakeCheckmk()
        apply(site, "other", other=target(primary="other.example.org"))
        apply(site)
        self.assertFalse(checkmk(site).remove(WS, "target"))
        self.assertEqual(list(site.hosts), [name_of("other")])
        self.assertIn(f"~workspaces~{WS}", site.folders)
        checkmk(site).remove(WS, "other")
        self.assertEqual((site.hosts, site.rules), ({}, {}))
        self.assertNotIn(f"~workspaces~{WS}", site.folders)
        self.assertEqual(site.pending, 0)

    def test_remove_of_an_unknown_host_changes_nothing(self) -> None:
        site = FakeCheckmk()
        apply(site, "other", other=target(primary="other.example.org"))
        site.calls.clear()
        unknown = checkmk(site)
        self.assertFalse(unknown.remove(WS, "target"))
        self.assertFalse(unknown.changed)
        self.assertEqual(site.writes(), [])
        empty = FakeCheckmk()
        self.assertFalse(checkmk(empty).remove(WS, "target"))
        self.assertEqual(empty.writes(), [])

    def test_remove_of_an_unknown_host_keeps_an_empty_folder(self) -> None:
        site = FakeCheckmk()
        apply(site)
        site.hosts.clear()
        site.rules.clear()
        site.calls.clear()
        self.assertFalse(checkmk(site).remove(WS, "target"))
        self.assertEqual(site.writes(), [])
        self.assertIn(f"~workspaces~{WS}", site.folders)

    def test_a_foreign_rule_is_left_alone(self) -> None:
        site = FakeCheckmk()
        site.rules["f"] = FakeCheckmk._rule(
            "f",
            "active_checks:icmp",
            {
                "properties": {"description": "someone else"},
                "value_raw": "{}",
                "conditions": {},
            },
        )
        apply(site)
        checkmk(site).remove(WS, "target")
        self.assertEqual(list(site.rules), ["f"])


if __name__ == "__main__":
    unittest.main()
