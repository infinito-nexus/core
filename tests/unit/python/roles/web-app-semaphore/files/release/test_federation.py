from __future__ import annotations

import datetime
import importlib
import io
import json
import tempfile
import unittest
import unittest.mock as mock
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.openbao_client import OpenBaoClient

FILES = PROJECT_ROOT / "roles/web-app-semaphore/files/python"
ID = "0a1b2c3d-0000-4000-8000-00000000000a"
HOST = "2001:db8::1"
NOW = datetime.datetime(2026, 11, 27, 12, 0, tzinfo=datetime.UTC)
OTHER = "/etc/nginx/conf.d/federate.sha256"
RECORDED = "/srv/openresty/conf.d/federate.sha256"


def load(*parts):
    spec = spec_from_file_location(
        f"{'_'.join(parts)}_under_test", FILES.joinpath(*parts).with_suffix(".py")
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load("release", "federation")
monitoring = importlib.import_module(load("monitoring").converge_secrets.__module__)
TOKEN = f"platform/monitoring/federation/ws-{ID}/2001_db8__1"
DIGEST = f"monitoring/ws-{ID}/federation/2001_db8__1"
MARKER = f"monitoring/ws-{ID}/released/2001_db8__1"
MONITORED = f"platform/monitoring/inventory/ws-{ID}/hosts/2001_db8__1"
AGENT = f"monitoring/ws-{ID}/agent/2001_db8__1"
CLAIM = f"monitoring/ws-{ID}/releasing/2001_db8__1"
TENANT_CREATE_ONLY = ("/released/", "/releasing/")
PROOF = {"removed": {"federation_token": 1, "monitoring_agent": 1}}
APPLY = {
    "alias": f"ws-{ID}",
    "host": HOST,
    "action": "apply",
    "label": None,
    "entry": {"prometheus": True, "share": {"agent": True}},
}
APPLY_LOGIN = {
    "platform/monitoring/checkmk": {"username": "monitoring", "secret": "s"},
    "platform/monitoring/agent-key": {"public_key": "ssh-ed25519 AAAA key"},
    f"platform/monitoring/inventory/ws-{ID}": {"digest_file": RECORDED},
}


class FakeBao:
    """Args:
    entries: the KV v2 records ``{"<mount>/<path>": data}`` it starts with,
        as names or a mapping to their fields. A write to an existing one
        below ``TENANT_CREATE_ONLY`` answers 403, as OpenBao answers the tenant role, which holds
        ``create`` there but no ``update``.
    refused: the record every request on answers ``status``.
    status: the answer of ``refused``.
    sticky: the record a DELETE answers 204 for and keeps.
    """

    write_create_only = OpenBaoClient.write_create_only

    def __init__(self, entries, refused=None, status=403, sticky=None):
        self.entries = (
            dict(entries)
            if isinstance(entries, dict)
            else {entry: {} for entry in entries}
        )
        self.refused = refused
        self.status = status
        self.sticky = sticky
        self.calls = []

    def request(self, method, path, body):
        kind = "/metadata/" if "/metadata/" in path else "/data/"
        mount, _, rest = path.partition(kind)
        record = f"{mount}/{rest}"
        self.calls.append((method, kind.strip("/"), record))
        if record == self.refused:
            return self.status, {}
        if method == "DELETE":
            if record != self.sticky:
                self.entries.pop(record, None)
            return 204, {}
        if method == "POST":
            if record in self.entries and any(
                segment in record for segment in TENANT_CREATE_ONLY
            ):
                return 403, {"errors": ["permission denied"]}
            if record in self.entries:
                return 400, {"errors": ["check-and-set parameter did not match"]}
            self.entries[record] = body["data"]
            return 200, {}
        if record not in self.entries:
            return 404, {}
        return 200, {"data": {"data": self.entries[record]}}

    def write(self, mount, path, data):
        self.calls.append(("POST", "data", f"{mount}/{path}"))
        self.entries[f"{mount}/{path}"] = dict(data)

    def read_all(self, mount, path):
        return dict(self.entries[f"{mount}/{path}"])

    def list_tree(self, mount, prefix):
        return []


def run(bao, *argv, workspace=ID, host=HOST):
    out = io.StringIO()
    code = release.main(
        list(argv), {"WORKSPACE": workspace, "HOST": host}, out, bao, NOW
    )
    return code, out.getvalue()


def erased(bao):
    return [
        (method, record) for method, kind, record in bao.calls if kind == "metadata"
    ]


class ReleaseFederationTests(unittest.TestCase):
    def test_the_release_erases_the_token_and_the_digest_and_keeps_the_tombstone(
        self,
    ):
        other = f"monitoring/ws-{ID}/federation/other"
        bao = FakeBao({TOKEN, DIGEST, AGENT, MARKER, CLAIM, MONITORED, other})
        self.assertEqual(run(bao, "erase"), (0, ""))
        self.assertEqual(set(bao.entries), {MARKER, CLAIM, MONITORED, other})
        self.assertEqual(
            erased(bao),
            [
                ("DELETE", TOKEN),
                ("GET", TOKEN),
                ("DELETE", DIGEST),
                ("GET", DIGEST),
                ("DELETE", AGENT),
                ("GET", AGENT),
            ],
        )

    def test_a_second_release_finds_nothing_and_passes(self):
        self.assertEqual(run(FakeBao(set()), "erase"), (0, ""))

    def test_a_failed_token_erase_stops_and_the_rerun_retries(self):
        bao = FakeBao({TOKEN, DIGEST, MARKER}, refused=TOKEN, status=503)
        code, out = run(bao, "erase")
        self.assertEqual(code, 1)
        line = json.loads(out)
        self.assertEqual((line["host"], line["released"]), (HOST, False))
        self.assertIn(f"erasing {TOKEN} answered 503", line["failed"])
        self.assertEqual(erased(bao), [("DELETE", TOKEN)])
        self.assertEqual(set(bao.entries), {TOKEN, DIGEST, MARKER})
        self.assertEqual(run(bao, "marked"), (0, ""))
        bao.refused = None
        bao.calls.clear()
        self.assertEqual(run(bao, "erase"), (0, ""))
        self.assertEqual(set(bao.entries), {MARKER})

    def test_a_token_still_present_after_its_delete_stops_the_erase(self):
        bao = FakeBao({TOKEN, DIGEST, MARKER}, sticky=TOKEN)
        code, out = run(bao, "erase")
        self.assertEqual(code, 1)
        self.assertIn(f"{TOKEN} still answers 200", json.loads(out)["failed"])
        self.assertEqual(erased(bao), [("DELETE", TOKEN), ("GET", TOKEN)])
        self.assertIn(DIGEST, bao.entries)

    def mark(self, bao):
        with tempfile.TemporaryDirectory() as scratch:
            share = Path(scratch) / "share.json"
            share.write_text(json.dumps(PROOF), encoding="utf-8")
            return run(bao, "mark", str(share))

    def test_mark_records_the_proof_and_its_time(self):
        bao = FakeBao(set())
        self.assertEqual(self.mark(bao), (0, ""))
        self.assertEqual(
            bao.entries[MARKER], {"proof": PROOF, "at": "2026-11-27T12:00:00+00:00"}
        )

    def test_mark_keeps_the_marker_of_an_earlier_run(self):
        bao = FakeBao({MARKER})
        self.assertEqual(self.mark(bao), (0, ""))
        self.assertEqual(bao.entries[MARKER], {})
        self.assertNotIn("POST", [method for method, _, _ in bao.calls])

    def test_a_refused_marker_fails_with_the_release_line(self):
        code, out = self.mark(FakeBao(set(), refused=MARKER))
        self.assertEqual(code, 1)
        self.assertIn(f"reading {MARKER} answered 403", json.loads(out)["failed"])

    def test_marked_passes_with_the_tombstone_alone(self):
        for left in ({MARKER, TOKEN, DIGEST}, {MARKER}):
            with self.subTest(left=left):
                self.assertEqual(run(FakeBao(left), "marked"), (0, ""))

    def test_no_tombstone_fails_loud_whatever_records_are_left(self):
        for left in ({TOKEN, DIGEST}, {TOKEN}, {DIGEST}, set()):
            with self.subTest(left=left):
                code, out = run(FakeBao(left), "marked")
                self.assertEqual(code, 1)
                failed = json.loads(out)["failed"]
                self.assertIn(f"{HOST} refuses the platform key", failed)
                self.assertIn(
                    "remove the agent binary, the monitoring key line and the "
                    "federation digest file manually",
                    failed,
                )

    def claim(self, bao, current=OTHER, action="claim"):
        with tempfile.TemporaryDirectory() as scratch:
            out = Path(scratch) / "digest-files"
            code, line = run(bao, action, str(out), current)
            if not out.exists():
                return code, line, None
            written = out.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return code, line, written

    def test_the_release_also_checks_the_digest_file_of_the_present_core(self):
        bao = FakeBao({MONITORED: {"digest_files": [RECORDED]}})
        self.assertEqual(self.claim(bao), (0, "", f"{RECORDED} {OTHER}\n"))
        self.assertEqual(self.claim(FakeBao(set()), current=OTHER), (0, "", "\n"))

    def test_negative_control_a_present_core_naming_no_digest_file_fails(self):
        for current in ("/etc/passwd", "relative/federate.sha256", ""):
            with self.subTest(current=current):
                bao = FakeBao({MONITORED: {"digest_files": [RECORDED]}})
                code, line, written = self.claim(bao, current=current)
                self.assertEqual((code, written), (1, None))
                self.assertIn("the present core names", json.loads(line)["failed"])

    def test_the_release_checks_every_digest_file_the_platform_record_names(self):
        for tenant in ({}, {DIGEST: {"digest_file": OTHER}}):
            with self.subTest(tenant=tenant):
                bao = FakeBao(
                    {
                        MONITORED: {"digest_files": [OTHER, RECORDED]},
                        MARKER: {"digest_file": "/x/federate.sha256"},
                        **tenant,
                    }
                )
                self.assertEqual(self.claim(bao), (0, "", f"{OTHER} {RECORDED}\n"))

    def test_the_claim_is_written_before_the_platform_record_is_read(self):
        bao = FakeBao({MONITORED: {"digest_files": [RECORDED]}})
        self.assertEqual(self.claim(bao)[0], 0)
        self.assertEqual(bao.entries[CLAIM], {"at": "2026-11-27T12:00:00+00:00"})
        order = [(method, record) for method, _, record in bao.calls]
        self.assertLess(order.index(("POST", CLAIM)), order.index(("GET", MONITORED)))

    def test_the_digest_files_of_the_check_are_the_claimed_ones_without_a_claim(
        self,
    ):
        for entries in ({}, {MONITORED: {"digest_files": [RECORDED]}}):
            with self.subTest(entries=entries):
                bao = FakeBao(dict(entries))
                named = self.claim(bao, action="digest-files")
                self.assertNotIn(CLAIM, bao.entries)
                self.assertNotIn("POST", [method for method, _, _ in bao.calls])
                self.assertEqual(named, self.claim(bao))
                self.assertIn(CLAIM, bao.entries)

    def test_a_claim_of_an_earlier_run_is_kept(self):
        bao = FakeBao({CLAIM: {"at": "earlier"}})
        self.assertEqual(self.claim(bao), (0, "", "\n"))
        self.assertEqual(bao.entries[CLAIM], {"at": "earlier"})

    def test_a_never_monitored_host_names_no_digest_file(self):
        for entries in (
            set(),
            {DIGEST: {"digest_file": RECORDED}},
            {MARKER: {"digest_file": RECORDED}},
        ):
            with self.subTest(entries=entries):
                self.assertEqual(self.claim(FakeBao(entries)), (0, "", "\n"))

    def test_a_platform_record_naming_no_digest_file_fails_loud(self):
        for record in (
            {},
            {"digest_files": []},
            {"digest_files": RECORDED},
            {"digest_file": RECORDED},
            {"digest_files": [RECORDED, "/etc/passwd"]},
        ):
            with self.subTest(record=record):
                code, line, written = self.claim(FakeBao({MONITORED: record}))
                self.assertEqual((code, written), (1, None))
                self.assertIn("no digest file", json.loads(line)["failed"])

    def test_a_platform_record_read_that_fails_fails_the_release(self):
        code, line, written = self.claim(FakeBao(set(), refused=MONITORED))
        self.assertEqual((code, written), (1, None))
        self.assertIn(f"reading {MONITORED} answered 403", json.loads(line)["failed"])

    def test_a_workspace_of_no_segment_refuses_before_any_request(self):
        for workspace in ("a?list=true#x", "../x", f"{ID}/../x", "", "%2e%2e", "a\nb"):
            for action in (
                ("erase",),
                ("marked",),
                ("claim", "/dev/null", OTHER),
                ("digest-files", "/dev/null", OTHER),
            ):
                with self.subTest(workspace=workspace, action=action):
                    bao = FakeBao(set())
                    code, line = run(bao, *action, workspace=workspace)
                    self.assertEqual(code, 1)
                    self.assertIn(
                        "is no OpenBao path segment", json.loads(line)["failed"]
                    )
                    self.assertEqual(bao.calls, [])

    def test_an_ambiguous_host_fails_before_any_request(self):
        for host, finding in (
            (".", "no host address or name"),
            ("." * 2, "no host address or name"),
            ("01.2.3.4", "ambiguous legacy IPv4 form"),
            ("127.1", "ambiguous legacy IPv4 form"),
            ("0x7f000001", "ambiguous legacy IPv4 form"),
        ):
            for action in (("erase",), ("marked",), ("claim", "/dev/null", OTHER)):
                with self.subTest(host=host, action=action):
                    bao = FakeBao(set())
                    out = io.StringIO()
                    code = release.main(
                        list(action), {"WORKSPACE": ID, "HOST": host}, out, bao, NOW
                    )
                    self.assertEqual((code, bao.calls), (1, []))
                    self.assertIn(finding, json.loads(out.getvalue())["failed"])

    def test_every_spelling_of_a_host_names_the_paths_apply_wrote(self):
        for host in ("2001:DB8::1", "2001:db8:0::1", "2001:0db8::1"):
            with self.subTest(host=host):
                bao = FakeBao(set())
                run(bao, "erase", host=host)
                paths = [record for _, _, record in bao.calls]
                self.assertTrue(paths)
                for path in paths:
                    self.assertTrue(path.endswith("/2001_db8__1"), path)

    def test_a_recorded_path_that_is_no_digest_file_fails(self):
        for recorded in (
            "/etc/passwd",
            "relative/federate.sha256",
            "/etc/../root/federate.sha256",
            "/etc/x y/federate.sha256",
            "/etc/x;rm/federate.sha256",
        ):
            with self.subTest(recorded=recorded):
                code, line, written = self.claim(
                    FakeBao({MONITORED: {"digest_files": [recorded]}})
                )
                self.assertEqual((code, written), (1, None))
                self.assertIn("no digest file", json.loads(line)["failed"])

    def test_an_apply_a_release_claims_meanwhile_refuses_and_the_release_sees_none(
        self,
    ):
        bao = FakeBao(APPLY_LOGIN)
        digest_file = monitoring.workspace_digest_file
        claimed = []

        def release_meanwhile(client, alias):
            claimed.append(self.claim(client))
            return digest_file(client, alias)

        with (
            mock.patch.object(monitoring, "workspace_digest_file", release_meanwhile),
            self.assertRaisesRegex(monitoring.RefusalError, "was released in"),
        ):
            monitoring.converge_secrets(bao, APPLY, lambda: "m1nted")
        self.assertEqual(claimed, [(0, "", "\n")])
        self.assertEqual(bao.entries[MONITORED], {"digest_files": [RECORDED]})
        for path in (TOKEN, DIGEST, AGENT):
            self.assertNotIn(path, bao.entries)

    def test_a_release_after_the_apply_wrote_its_record_reads_it(self):
        bao = FakeBao(APPLY_LOGIN)
        monitoring.converge_secrets(bao, APPLY, lambda: "m1nted")
        self.assertEqual(self.claim(bao, current=RECORDED), (0, "", f"{RECORDED}\n"))
        with self.assertRaisesRegex(monitoring.RefusalError, "was released in"):
            monitoring.converge_secrets(bao, APPLY, lambda: "m1nted")

    def test_the_records_are_the_ones_the_monitoring_template_writes(self):
        alias = f"ws-{ID}"
        host = monitoring.path_host(HOST)
        self.assertEqual(
            release.records(ID, HOST),
            [
                (
                    monitoring.MOUNT,
                    monitoring.FEDERATION_PATH.format(alias=alias, host=host),
                ),
                (
                    monitoring.DIGEST_MOUNT,
                    monitoring.DIGEST_PATH.format(alias=alias, host=host),
                ),
                (
                    monitoring.DIGEST_MOUNT,
                    monitoring.AGENT_KEY_PATH.format(alias=alias, host=host),
                ),
            ],
        )
        self.assertEqual(
            release.marker(ID, HOST),
            (
                monitoring.DIGEST_MOUNT,
                monitoring.RELEASED_PATH.format(alias=alias, host=host),
            ),
        )
        self.assertEqual(
            CLAIM,
            f"{monitoring.DIGEST_MOUNT}/"
            + monitoring.RELEASING_PATH.format(alias=alias, host=host),
        )
        self.assertEqual(
            release.monitored(ID, HOST),
            (monitoring.MOUNT, f"monitoring/inventory/{alias}/hosts/{host}"),
        )


if __name__ == "__main__":
    unittest.main()
