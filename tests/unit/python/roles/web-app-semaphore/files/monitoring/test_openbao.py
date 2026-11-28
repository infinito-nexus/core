from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils import PROJECT_ROOT
from utils.platform_monitoring import configuration_base, digest_path

from ._fake_monitoring import (
    AGENT_KEY,
    DIGEST,
    ID,
    INVENTORY,
    LABEL,
    LOGIN,
    MONITORED,
    OTHER_DIGEST,
    OTHER_TOKEN,
    PARENT,
    PUBLIC_KEY,
    RELEASED,
    RELEASING,
    TLS_DAYS,
    TOKEN,
    WORKSPACE_DIGEST_FILE,
    WS,
    FakeBao,
    FakeCheckmk,
    Interleaved,
    RefusalError,
    RunError,
    checkmk,
    claim_release,
    converge,
    env,
    erase_release,
    monitoring,
    openbao,
    planned_for,
    removed_plan,
    survey,
    target,
)

DIGEST_FILE = digest_path(configuration_base(PROJECT_ROOT))


class TestTheSecrets(unittest.TestCase):
    def test_a_segment_of_no_kind_refuses_before_any_request(self) -> None:
        for field, value in (
            ("alias", "ws-../x"),
            ("alias", f"{WS}/../x"),
            ("alias", f"{WS}?list=true"),
            ("label", PARENT),
            ("label", "a#b"),
            ("label", "a%2fb"),
            ("label", "a\nb"),
        ):
            with self.subTest(field=field, value=value):
                bao = FakeBao(LOGIN)
                planned = {**planned_for(), field: value}
                with self.assertRaisesRegex(RunError, "is no OpenBao path segment"):
                    converge(bao, planned)
                self.assertEqual((bao.reads, bao.writes), ([], []))

    def test_every_path_template_refuses_a_traversal_segment(self) -> None:
        for template in (
            openbao.FEDERATION_PATH,
            openbao.DIGEST_PATH,
            openbao.AGENT_KEY_PATH,
            openbao.RELEASED_PATH,
            openbao.RELEASING_PATH,
        ):
            for value in ("", ".", PARENT, "target/../x", "target?x", "%2e", "A"):
                with (
                    self.subTest(template=template, host=value),
                    self.assertRaises(RunError),
                ):
                    openbao.bao_path(template, alias=WS, host=value)
            for value in ("", PARENT, "ws-x", f"{WS}/x", f"{WS}?x", f"{WS}#x"):
                with (
                    self.subTest(template=template, alias=value),
                    self.assertRaises(RunError),
                ):
                    openbao.bao_path(template, alias=value, host="target")
            self.assertEqual(
                openbao.bao_path(template, alias=WS, host="2001_db8__1"),
                template.format(alias=WS, host="2001_db8__1"),
            )

    def test_a_new_host_gets_a_token_digest_and_the_agent_key(self) -> None:
        bao = FakeBao(LOGIN)
        found = converge(bao)
        self.assertEqual(found["token"], "m1nted")
        self.assertEqual(bao.entries[TOKEN], {"token": "m1nted"})
        self.assertEqual(
            bao.entries[DIGEST],
            {"federation_token_sha256": hashlib.sha256(b"m1nted").hexdigest()},
        )
        self.assertEqual(
            bao.entries[MONITORED], {"digest_files": [WORKSPACE_DIGEST_FILE]}
        )
        self.assertEqual(bao.entries[AGENT_KEY], {"public_key": PUBLIC_KEY})

    def test_the_digest_file_is_the_workspace_cores_not_the_runners(self) -> None:
        self.assertNotEqual(WORKSPACE_DIGEST_FILE, DIGEST_FILE)
        bao = FakeBao(LOGIN)
        converge(bao)
        self.assertEqual(
            bao.entries[MONITORED]["digest_files"], [WORKSPACE_DIGEST_FILE]
        )

    def test_a_core_upgrade_keeps_every_digest_file_ever_written(self) -> None:
        old = "/etc/nginx/conf.d/federate.sha256"
        bao = FakeBao({**LOGIN, MONITORED: {"digest_files": [old]}})
        converge(bao)
        self.assertEqual(
            bao.entries[MONITORED],
            {"digest_files": sorted([old, WORKSPACE_DIGEST_FILE])},
        )
        bao.writes.clear()
        converge(bao)
        self.assertEqual(bao.writes, [])

    def test_a_host_without_any_share_is_still_recorded_as_monitored(self) -> None:
        bao = FakeBao(LOGIN)
        converge(
            bao,
            planned_for(
                target=target(
                    {"agent": False, "health": False, "system": False, "traffic": False}
                )
            ),
        )
        self.assertEqual(
            bao.entries[MONITORED], {"digest_files": [WORKSPACE_DIGEST_FILE]}
        )
        self.assertNotIn(DIGEST, bao.entries)

    def test_an_apply_without_the_workspace_digest_file_refuses_before_any_write(
        self,
    ) -> None:
        for held in ({}, {"digest_file": "/etc/passwd"}):
            with self.subTest(held=held):
                bao = FakeBao({**LOGIN, INVENTORY: {"private_key": "k", **held}})
                with self.assertRaisesRegex(RefusalError, "run workspace apply for"):
                    converge(bao)
                self.assertEqual(bao.writes, [])

    def test_a_runner_core_without_platform_monitoring_refuses_by_name(self) -> None:
        bao = FakeBao({**LOGIN, INVENTORY: {"private_key": "k", "digest_file": ""}})
        with self.assertRaisesRegex(
            RefusalError, "has no platform monitoring: select a newer core"
        ):
            converge(bao)
        self.assertEqual(bao.writes, [])

    def test_an_apply_on_a_released_host_refuses_before_any_write(self) -> None:
        bao = FakeBao({**LOGIN, RELEASED: {"proof": {}, "at": "earlier"}})
        with self.assertRaisesRegex(
            RefusalError,
            f"host target was released in {WS}: use a new host name or destroy"
            " the workspace",
        ):
            converge(bao)
        self.assertEqual(bao.writes, [])
        self.assertEqual(
            openbao.RELEASED_PATH.format(alias=WS, host="target"),
            RELEASED.removeprefix("monitoring/"),
        )

    def test_an_empty_tombstone_or_claim_refuses_by_its_existence(self) -> None:
        for marker in (RELEASED, RELEASING):
            for held in ({}, {"proof": {}, "at": "earlier"}):
                with self.subTest(marker=marker, held=held):
                    bao = FakeBao({**LOGIN, marker: held})
                    with self.assertRaisesRegex(RefusalError, "was released in"):
                        converge(bao)
                    self.assertEqual(bao.writes, [])

    def test_a_tombstone_read_that_fails_refuses_closed(self) -> None:
        for marker in (RELEASED, RELEASING):
            for status in (403, 500, 503):
                with self.subTest(marker=marker, status=status):
                    bao = FakeBao(LOGIN, failing={marker: status})
                    with self.assertRaisesRegex(RunError, f"answered {status}"):
                        converge(bao)
                    self.assertEqual(bao.writes, [])

    def test_an_unreachable_openbao_fails_the_preflight(self) -> None:
        class Unreachable(FakeBao):
            def request(self, method, path, body):
                raise ConnectionError("unreachable")

        planned = planned_for()
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps(planned), encoding="utf-8")
            code = monitoring.main(
                ["preflight", str(plan), str(Path(tmp) / "login.json")],
                env(),
                stdout=io.StringIO(),
                bao=(ConnectionError, Unreachable(LOGIN)),
            )
        self.assertEqual(code, 1)

    def test_an_apply_a_release_claims_meanwhile_refuses_after_its_record(
        self,
    ) -> None:
        bao = FakeBao(LOGIN)
        digest_file = openbao.workspace_digest_file

        def claimed_meanwhile(client, alias):
            client.entries[RELEASING] = {"at": "meanwhile"}
            return digest_file(client, alias)

        with (
            mock.patch.object(openbao, "workspace_digest_file", claimed_meanwhile),
            self.assertRaisesRegex(RefusalError, "was released in"),
        ):
            converge(bao)
        self.assertEqual(
            bao.entries[MONITORED], {"digest_files": [WORKSPACE_DIGEST_FILE]}
        )
        for path in (TOKEN, DIGEST, AGENT_KEY):
            self.assertNotIn(path, bao.entries)

    def test_no_interleaving_of_apply_and_release_leaves_a_secret_behind(self) -> None:
        steps = Interleaved(LOGIN, {})
        converge(steps)
        total = steps.ops
        for claim in range(total + 1):
            for erase in range(claim, total + 1):
                with self.subTest(claim=claim, erase=erase):
                    events = {claim: [claim_release]}
                    events.setdefault(erase, []).append(erase_release)
                    bao = Interleaved(LOGIN, events)
                    try:
                        converge(bao)
                    except RefusalError:
                        self.assertNotIn(LABEL, bao.entries)
                    if erase >= bao.ops:
                        claim_release(bao)
                        erase_release(bao)
                    for path in (TOKEN, DIGEST, AGENT_KEY):
                        self.assertNotIn(path, bao.entries)

    def test_settle_exits_3_once_a_release_claimed_the_host(self) -> None:
        for entries, code in (
            (LOGIN, 0),
            ({**LOGIN, RELEASING: {}}, 3),
            ({**LOGIN, RELEASED: {}}, 3),
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                plan = Path(tmp) / "plan.json"
                plan.write_text(json.dumps(planned_for()), encoding="utf-8")
                self.assertEqual(
                    monitoring.main(
                        ["settle", str(plan)],
                        env(),
                        stdout=io.StringIO(),
                        bao=(LookupError, FakeBao(entries)),
                    ),
                    code,
                )

    def test_the_agent_key_mirror_is_per_host_and_goes_without_the_agent(
        self,
    ) -> None:
        other = f"monitoring/{WS}/agent/other"
        bao = FakeBao({**LOGIN, other: {"public_key": PUBLIC_KEY}})
        converge(bao)
        self.assertEqual(bao.entries[AGENT_KEY], {"public_key": PUBLIC_KEY})
        converge(bao, planned_for(target=target({"agent": False})))
        self.assertNotIn(AGENT_KEY, bao.entries)
        self.assertIn(other, bao.entries)
        self.assertEqual(
            survey.SHARE.agent_key_reference(ID, "target"),
            {"openbao": f"{AGENT_KEY}#public_key"},
        )

    def test_remove_keeps_the_monitored_record_for_a_later_release(self) -> None:
        bao = FakeBao(
            {
                **LOGIN,
                TOKEN: {"token": "t"},
                DIGEST: {"federation_token_sha256": "d"},
                MONITORED: {"digest_files": ["/x/federate.sha256"]},
                AGENT_KEY: {"public_key": PUBLIC_KEY},
                RELEASED: {"proof": {}, "at": "earlier"},
            }
        )
        converge(bao, removed_plan())
        self.assertNotIn(TOKEN, bao.entries)
        self.assertNotIn(DIGEST, bao.entries)
        self.assertNotIn(AGENT_KEY, bao.entries)
        self.assertEqual(
            bao.entries[MONITORED], {"digest_files": ["/x/federate.sha256"]}
        )
        self.assertFalse([write for write in bao.writes if MONITORED in write])

    def test_a_host_monitored_before_its_record_existed_gets_it_alone(self) -> None:
        digest = hashlib.sha256(b"old").hexdigest()
        bao = FakeBao(
            {
                **LOGIN,
                TOKEN: {"token": "old"},
                DIGEST: {"federation_token_sha256": digest},
                AGENT_KEY: {"public_key": PUBLIC_KEY},
                LABEL: {"host": "target"},
            }
        )
        converge(bao)
        self.assertEqual(bao.writes, [MONITORED])
        self.assertEqual(
            bao.entries[MONITORED], {"digest_files": [WORKSPACE_DIGEST_FILE]}
        )

    def test_a_second_run_writes_nothing(self) -> None:
        bao = FakeBao(LOGIN)
        converge(bao)
        bao.writes.clear()
        converge(bao)
        self.assertEqual(bao.writes, [])

    def test_a_stale_digest_is_rewritten_and_the_token_kept(self) -> None:
        bao = FakeBao(
            {
                **LOGIN,
                TOKEN: {"token": "old"},
                DIGEST: {"federation_token_sha256": "x"},
                MONITORED: {"digest_files": [WORKSPACE_DIGEST_FILE]},
                AGENT_KEY: {"public_key": PUBLIC_KEY},
                LABEL: {"host": "target"},
            }
        )
        self.assertEqual(converge(bao)["token"], "old")
        self.assertEqual(bao.writes, [DIGEST])

    def test_a_host_that_stopped_sharing_loses_only_its_token_and_digest(self) -> None:
        others = {
            OTHER_TOKEN: {"token": "o"},
            OTHER_DIGEST: {"federation_token_sha256": "d"},
        }
        bao = FakeBao({**LOGIN, **others})
        converge(bao)
        quiet = planned_for(
            target=target({"health": False, "system": False, "traffic": False})
        )
        self.assertIsNone(converge(bao, quiet)["token"])
        self.assertNotIn(TOKEN, bao.entries)
        self.assertNotIn(DIGEST, bao.entries)
        self.assertEqual(
            bao.entries[MONITORED], {"digest_files": [WORKSPACE_DIGEST_FILE]}
        )
        for path in others:
            self.assertIn(path, bao.entries)

    def test_remove_erases_that_host_alone_and_an_unknown_host_writes_nothing(
        self,
    ) -> None:
        bao = FakeBao(
            {
                **LOGIN,
                TOKEN: {"token": "t"},
                DIGEST: {"federation_token_sha256": "d"},
                OTHER_TOKEN: {"token": "o"},
            }
        )
        removed = removed_plan()
        converge(bao, removed)
        self.assertNotIn(TOKEN, bao.entries)
        self.assertIn(OTHER_TOKEN, bao.entries)
        bao.writes.clear()
        converge(bao, removed)
        self.assertEqual(bao.writes, [])

    def test_a_host_without_agent_reads_no_agent_key(self) -> None:
        bao = FakeBao(LOGIN)
        converge(bao, planned_for(target=target({"agent": False})))
        self.assertNotIn("platform/monitoring/agent-key", bao.reads)
        self.assertNotIn(AGENT_KEY, bao.entries)

    def test_the_secrets_file_is_private_and_off_stdout(self) -> None:
        bao = FakeBao(
            {
                **LOGIN,
                "platform/monitoring/checkmk": {
                    "username": "monitoring",
                    "secret": "s3cret",
                },
                TOKEN: {"token": "t0ken"},
            }
        )
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps(planned_for()))
            target_file = Path(tmp) / "secrets.json"
            code = monitoring.main(
                ["secrets", str(plan), str(target_file)],
                env(),
                stdout=out,
                bao=(LookupError, bao),
            )
            self.assertEqual(code, 0)
            self.assertEqual(target_file.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("t0ken", out.getvalue())
        self.assertNotIn("s3cret", out.getvalue())

    def test_remove_erases_the_label_bindings_of_that_host_alone(self) -> None:
        other = f"monitoring/{WS}/labels/shop"
        bao = FakeBao({**LOGIN, LABEL: {"host": "target"}, other: {"host": "other"}})
        converge(bao, removed_plan())
        self.assertNotIn(LABEL, bao.entries)
        self.assertEqual(bao.entries[other], {"host": "other"})
        self.assertEqual(bao.writes, [f"DELETE {LABEL}"])

    def test_a_concurrent_apply_binding_the_label_first_wins(self) -> None:
        class Racing(FakeBao):
            def write_create_only(self, mount, path, data):
                if f"{mount}/{path}" == LABEL:
                    self.entries.setdefault(LABEL, {"host": "other"})
                return super().write_create_only(mount, path, data)

        bao = Racing(LOGIN)
        with self.assertRaisesRegex(
            RefusalError, "DNS_LABEL target is bound to host other"
        ):
            converge(bao)
        self.assertEqual(bao.entries[LABEL], {"host": "other"})
        self.assertEqual(bao.writes, [])

    def test_a_refusal_after_the_secrets_converges_on_the_rerun(self) -> None:
        bao = FakeBao(LOGIN)
        planned = planned_for()
        first = converge(bao, planned)
        written = dict(bao.entries)
        site = FakeCheckmk()
        site.foreign = ["cmkadmin"]
        with self.assertRaisesRegex(RefusalError, "another user"):
            checkmk(site).apply(planned, TLS_DAYS)
        self.assertEqual(site.writes(), [])
        bao.writes.clear()
        site.foreign = []
        second = converge(bao, planned)
        self.assertEqual((bao.writes, bao.entries), ([], written))
        self.assertEqual(second["token"], first["token"])
        self.assertTrue(checkmk(site).apply(planned, TLS_DAYS))

    def test_negative_control_apply_keeps_the_label_binding(self) -> None:
        bao = FakeBao({**LOGIN, LABEL: {"host": "target"}})
        converge(bao)
        self.assertEqual(bao.entries[LABEL], {"host": "target"})

    def test_apply_binds_the_label_to_monitor_host_once(self) -> None:
        bao = FakeBao(LOGIN)
        converge(bao)
        self.assertEqual(bao.entries[LABEL], {"host": "target"})
        bao.writes.clear()
        converge(bao)
        self.assertNotIn(LABEL, bao.writes)


if __name__ == "__main__":
    unittest.main()
