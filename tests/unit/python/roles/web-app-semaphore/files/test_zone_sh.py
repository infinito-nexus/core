from __future__ import annotations

import fcntl
import json
import sys
import unittest

from utils.cache.files import read_text

from .provision._fake_provision import (
    ACCOUNT_ID,
    FILES,
    LOCK_ID,
    WORKSPACE,
    ZONE_TOKEN,
    Sandbox,
)

DOMAIN = "shop-customer.example"
ZONE_ID = "023e105f4ecef8ad9ca31a8372d0c353"
NAME_SERVERS = ["ada.ns.cloudflare.com", "bob.ns.cloudflare.com"]
STATE_OBJECT = f"{WORKSPACE}-state/SO-2026/1.zone.tfstate"
LOCK_OBJECT = f"{STATE_OBJECT}.tflock"
STALE_LOCK = json.dumps({"ID": LOCK_ID}).encode()
CREATE = {"ZONE_ACTION": "create", "DOMAIN": DOMAIN}
CHECKOUT_MARKER = "pwplantedcheckout"
HELD = {
    "state": ["cloudflare_zone.zone"],
    "outputs": {
        "zone": {"value": DOMAIN},
        "zone_id": {"value": ZONE_ID},
        "status": {"value": "pending"},
        "name_servers": {"value": NAME_SERVERS},
    },
    "show": {
        "values": {
            "root_module": {
                "resources": [
                    {"address": "cloudflare_zone.zone", "values": {"name": DOMAIN}}
                ]
            }
        }
    },
}
ECHOING_TOFU = """#!/bin/sh
echo "$CLOUDFLARE_API_TOKEN" >&2
exec {python} {real} "$@"
"""
LOCK_PROBING_TOFU = """#!/bin/sh
{python} -c '
import fcntl, sys
for path in sys.argv[1:]:
    with open(path, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print("free", path, file=sys.stderr)
        except BlockingIOError:
            print("held", path, file=sys.stderr)
' {own} {other}
exec {python} {real} "$@"
"""
DELETE = {"ZONE_ACTION": "delete"}
UNLOCK = {"ZONE_ACTION": "unlock"}
SHOW = {"ZONE_ACTION": "show", "DOMAIN": DOMAIN}


def last_line(result):
    return json.loads(result.stdout.splitlines()[-1])


def checkout_findings(calls):
    """Args:
        calls: the tofu calls of a run whose checkout holds ``CHECKOUT_MARKER``.

    Returns:
        Every file a tofu call found staged that carries the marker.
    """
    return sorted(
        {
            f"tofu {call['argv'][0]} stages {name}"
            for call in calls
            for name, text in call["texts"].items()
            if CHECKOUT_MARKER in text
        }
    )


def token_findings(result, calls, environment, token):
    """Args:
        result: the finished zone.sh run.
        calls: the tofu calls of the run.
        environment: the task environment the run started with.
        token: the zone token OpenBao holds.

    Returns:
        Every task output, tofu argument, staged file and task environment
        value of the run that carries the token.
    """
    findings = [
        f"the task {stream} carries the token"
        for stream, text in (("stdout", result.stdout), ("stderr", result.stderr))
        if token in text
    ]
    for call in calls:
        command = call["argv"][0]
        findings += [
            f"tofu {command} takes the token" for a in call["argv"] if token in a
        ]
        findings += [
            f"tofu {command} stages {name} with the token"
            for name, text in call["texts"].items()
            if token in text
        ]
    findings += [
        f"the task environment holds the token in {name}"
        for name, value in environment.items()
        if token in value
    ]
    return findings


class ZoneCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox("knot", locks=True)
        self.addCleanup(self.sandbox.close)
        self.sandbox.set_plan({"state": [], "outputs": HELD["outputs"]})

    def call(self, command):
        return next(c for c in self.sandbox.calls() if c["argv"][0] == command)

    def hold(self, outputs=None):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        plan = json.loads(json.dumps(HELD))
        plan["outputs"].update(outputs or {})
        self.sandbox.set_plan(plan)

    def wrap_tofu(self, template, **fields):
        tofu = self.sandbox.bin / "tofu"
        real = self.sandbox.bin / "tofu-real"
        tofu.rename(real)
        text = template.format(python=sys.executable, real=real, **fields)
        tofu.write_text(text, encoding="utf-8")
        tofu.chmod(0o755)

    def line_lock(self, line):
        locks = self.sandbox.tmp / "provision-locks"
        locks.mkdir(mode=0o700, exist_ok=True)
        return locks / f"{WORKSPACE}.SO-2026-{line}.zone.lock"


class TestInputs(ZoneCase):
    def test_zone_sh_refuses_each_malformed_input(self):
        cases = {
            "argument": (("extra",), CREATE),
            "ZONE_ACTION": ((), {**CREATE, "ZONE_ACTION": "destroy"}),
            "SALES_ORDER": ((), {**CREATE, "SALES_ORDER": "1SO"}),
            "LINE": ((), {**CREATE, "LINE": "01"}),
            "DOMAIN": ((), {**CREATE, "DOMAIN": "Shop.Example"}),
            "DOMAIN is not taken": ((), {"ZONE_ACTION": "delete", "DOMAIN": DOMAIN}),
        }
        for name, (arguments, values) in cases.items():
            with self.subTest(name=name):
                result = self.sandbox.run("zone", *arguments, **values)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(name, result.stderr)
                self.assertEqual(self.sandbox.calls(), [])
                self.assertEqual(self.sandbox.platform.reads, [])
                self.assertEqual(self.sandbox.platform.cloudflare_requests, [])

    def test_show_needs_a_domain(self):
        result = self.sandbox.run("zone", ZONE_ACTION="show")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("DOMAIN is missing", result.stderr)
        self.assertEqual(self.sandbox.calls(), [])

    def test_zone_sh_reads_no_file_of_the_checkout(self):
        (self.sandbox.checkout / "main.tf.json").write_text(
            json.dumps({"locals": {"planted": CHECKOUT_MARKER}}), encoding="utf-8"
        )
        self.sandbox.tfvars({"dns_label": CHECKOUT_MARKER})
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(checkout_findings(self.sandbox.calls()), [])
        self.assertEqual(
            json.loads(self.call("apply")["texts"]["values.tfvars.json"]),
            {"domain": DOMAIN},
        )

    def test_negative_control_a_template_that_reads_the_checkout_is_caught(self):
        self.sandbox.tfvars({"dns_label": CHECKOUT_MARKER})
        self.sandbox.run("provision")
        self.assertIn(
            "tofu init stages values.tfvars.json",
            checkout_findings(self.sandbox.calls()),
        )


class TestToken(ZoneCase):
    def test_the_zone_token_reaches_no_output(self):
        environment = self.sandbox.environment(**CREATE)
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.sandbox.calls()
        self.assertEqual(token_findings(result, calls, environment, ZONE_TOKEN), [])
        self.assertTrue(
            all(
                ZONE_TOKEN not in path
                for path in self.sandbox.platform.cloudflare_requests
            )
        )
        self.assertEqual(self.call("apply")["env"]["CLOUDFLARE_API_TOKEN"], ZONE_TOKEN)

    def test_negative_control_a_planted_echo_of_the_token_is_caught(self):
        self.wrap_tofu(ECHOING_TOFU)
        environment = self.sandbox.environment(**CREATE)
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "the task stderr carries the token",
            token_findings(result, self.sandbox.calls(), environment, ZONE_TOKEN),
        )


class TestZoneState(ZoneCase):
    def test_the_zone_state_has_its_own_key(self):
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        init = self.call("init")
        self.assertIn(f'bucket = "{WORKSPACE}-state"\n', init["backend"]["text"])
        self.assertIn('key = "SO-2026/1.zone.tfstate"\n', init["backend"]["text"])
        self.assertEqual(init["backend"]["mode"], 0o600)
        versions = json.loads(init["texts"]["versions.tf.json"])
        self.assertIs(versions["terraform"]["backend"]["s3"]["use_lockfile"], True)
        self.assertEqual(
            init["texts"]["main.tf.json"],
            read_text(str(FILES / "opentofu" / "zone" / "main.tf.json")),
        )
        encryption = json.loads(init["env"]["TF_ENCRYPTION"])
        self.assertIs(encryption["state"]["enforced"], True)
        self.assertIs(encryption["plan"]["enforced"], True)

    def test_create_prints_exactly_the_zone_line(self):
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            last_line(result),
            {
                "zone": DOMAIN,
                "zone_id": ZONE_ID,
                "status": "pending",
                "name_servers": NAME_SERVERS,
            },
        )
        self.assertEqual(self.call("apply")["env"]["TF_VAR_account_id"], ACCOUNT_ID)

    def test_the_zone_run_logs_in_with_the_zone_role_only(self):
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sandbox.platform.logins, [f"{WORKSPACE}-zone"])

    def test_create_refuses_a_zone_the_account_already_holds(self):
        self.sandbox.platform.zones[DOMAIN] = {
            "id": ZONE_ID,
            "status": "active",
            "name_servers": NAME_SERVERS,
        }
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(f"already holds DOMAIN {DOMAIN}", result.stderr)
        self.assertEqual(self.sandbox.commands(), ["init"])
        self.assertNotIn(STATE_OBJECT, self.sandbox.platform.objects)

    def test_a_second_create_skips_the_check_of_its_own_zone(self):
        self.hold()
        self.sandbox.platform.zones[DOMAIN] = {
            "id": ZONE_ID,
            "status": "active",
            "name_servers": NAME_SERVERS,
        }
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.sandbox.commands(),
            ["init", "state", "output", "state", "apply", "output"],
        )
        self.assertEqual(self.sandbox.platform.cloudflare_requests, [])

    def test_create_refuses_another_zone_of_the_line(self):
        self.hold({"zone": {"value": "other.example"}})
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("holds the zone other.example", result.stderr)
        self.assertNotIn("apply", self.sandbox.commands())

    def test_show_reads_the_state_and_the_provider_and_writes_nothing(self):
        self.hold()
        self.sandbox.platform.zones[DOMAIN] = {
            "id": ZONE_ID,
            "status": "active",
            "name_servers": NAME_SERVERS,
        }
        result = self.sandbox.run("zone", ZONE_ACTION="show", DOMAIN=DOMAIN)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            last_line(result),
            {
                "zone": DOMAIN,
                "zone_id": ZONE_ID,
                "status": "active",
                "name_servers": NAME_SERVERS,
            },
        )
        self.assertEqual(self.sandbox.commands(), ["init", "state", "output"])
        self.assertNotIn(
            "PUT", [method for method, _ in self.sandbox.platform.s3_requests]
        )

    def test_show_refuses_a_line_without_a_zone(self):
        result = self.sandbox.run("zone", ZONE_ACTION="show", DOMAIN=DOMAIN)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("holds no zone", result.stderr)

    def test_delete_without_a_state_succeeds_with_nothing_to_do(self):
        result = self.sandbox.run("zone", ZONE_ACTION="delete")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(last_line(result), {"deleted": True, "zone": None})
        self.assertEqual(self.sandbox.commands(), ["init"])

    def interrupt(self, show, *extra):
        objects = self.sandbox.platform.objects
        for key in (STATE_OBJECT, *extra):
            objects[key] = STALE_LOCK if key == LOCK_OBJECT else b"encrypted"
        self.sandbox.set_plan({"state": HELD["state"], "outputs": {}, "show": show})
        return objects

    def test_delete_destroys_a_state_an_interrupted_create_left(self):
        objects = self.interrupt(HELD["show"])
        result = self.sandbox.run("zone", **DELETE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(last_line(result), {"deleted": True, "zone": DOMAIN})
        self.assertEqual(
            self.sandbox.commands(),
            ["init", "state", "show", "state", "destroy", "state"],
        )
        destroy = self.call("destroy")
        self.assertEqual(
            json.loads(destroy["texts"]["values.tfvars.json"]), {"domain": DOMAIN}
        )
        self.assertEqual(destroy["env"]["TF_VAR_account_id"], ACCOUNT_ID)
        self.assertEqual(destroy["env"]["CLOUDFLARE_API_TOKEN"], ZONE_TOKEN)
        self.assertNotIn(STATE_OBJECT, objects)

    def test_a_stale_lock_blocks_delete_until_unlock(self):
        objects = self.interrupt(HELD["show"], LOCK_OBJECT)
        locked = self.sandbox.run("zone", **DELETE)
        self.assertEqual(locked.returncode, 1, locked.stderr)
        self.assertIn("tofu destroy exited with 1", locked.stderr)
        self.assertEqual(
            self.sandbox.commands(), ["init", "state", "show", "state", "destroy"]
        )
        self.assertIn(STATE_OBJECT, objects)
        self.assertIn(LOCK_OBJECT, objects)
        unlocked = self.sandbox.run("zone", **UNLOCK)
        self.assertEqual(unlocked.returncode, 0, unlocked.stderr)
        self.assertNotIn(LOCK_OBJECT, objects)
        deleted = self.sandbox.run("zone", **DELETE)
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        self.assertEqual(last_line(deleted), {"deleted": True, "zone": DOMAIN})
        self.assertNotIn(STATE_OBJECT, objects)

    def test_negative_control_create_and_show_refuse_that_state(self):
        objects = self.interrupt(HELD["show"], LOCK_OBJECT)
        for action, values in (("create", CREATE), ("show", SHOW)):
            with self.subTest(action=action):
                result = self.sandbox.run("zone", **values)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(
                    "holds cloudflare_zone.zone without the outputs", result.stderr
                )
                self.assertEqual(self.sandbox.commands(), ["init", "state", "output"])
                self.assertIn(STATE_OBJECT, objects)
                self.assertIn(LOCK_OBJECT, objects)
        self.assertEqual(self.sandbox.platform.cloudflare_requests, [])

    def test_delete_keeps_a_state_it_cannot_read_the_zone_from(self):
        objects = self.interrupt(
            {"values": {"root_module": {"resources": []}}}, LOCK_OBJECT
        )
        result = self.sandbox.run("zone", **DELETE)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("names no cloudflare_zone.zone with a name", result.stderr)
        self.assertEqual(self.sandbox.commands(), ["init", "state", "show"])
        self.assertIn(STATE_OBJECT, objects)
        self.assertIn(LOCK_OBJECT, objects)

    def test_negative_control_a_state_without_resources_is_forgotten(self):
        objects = self.sandbox.platform.objects
        objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.set_plan({"state": [], "outputs": {}})
        result = self.sandbox.run("zone", **DELETE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(last_line(result), {"deleted": True, "zone": None})
        self.assertNotIn(STATE_OBJECT, objects)

    def test_delete_destroys_the_zone_state_only(self):
        self.hold()
        objects = self.sandbox.platform.objects
        server = f"{WORKSPACE}-state/SO-2026/1.tfstate"
        objects[server] = b"encrypted"
        result = self.sandbox.run("zone", ZONE_ACTION="delete")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(last_line(result), {"deleted": True, "zone": DOMAIN})
        self.assertEqual(
            json.loads(self.call("destroy")["texts"]["values.tfvars.json"]),
            {"domain": DOMAIN},
        )
        self.assertEqual(sorted(objects), [server])

    def test_unlock_force_unlocks_the_zone_state(self):
        self.sandbox.platform.objects[LOCK_OBJECT] = STALE_LOCK
        result = self.sandbox.run("zone", ZONE_ACTION="unlock")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.call("force-unlock")["argv"], ["force-unlock", "-force", LOCK_ID]
        )

    def test_unlock_refuses_while_a_task_of_the_workspace_runs(self):
        locks = self.sandbox.tmp / "provision-locks"
        locks.mkdir(mode=0o700)
        with (locks / f"{WORKSPACE}.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            result = self.sandbox.run("zone", ZONE_ACTION="unlock")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(f"a provision or destroy task of {WORKSPACE}", result.stderr)
        self.assertEqual(self.sandbox.calls(), [])


class TestLineLock(ZoneCase):
    def test_a_zone_task_holds_its_line_lock_while_tofu_runs(self):
        own, other = self.line_lock(1), self.line_lock(2)
        self.wrap_tofu(LOCK_PROBING_TOFU, own=own, other=other)
        for action, values in (("create", CREATE), ("delete", DELETE)):
            with self.subTest(action=action):
                result = self.sandbox.run("zone", **values)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"held {own}", result.stderr)
                self.assertIn(f"free {other}", result.stderr)

    def test_a_zone_task_refuses_while_another_of_its_line_runs(self):
        with self.line_lock(1).open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            for action, values in (
                ("create", CREATE),
                ("delete", DELETE),
                ("unlock", UNLOCK),
            ):
                with self.subTest(action=action):
                    result = self.sandbox.run("zone", **values)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("a zone task of SO-2026-1", result.stderr)
                    self.assertEqual(self.sandbox.calls(), [])

    def test_negative_control_a_task_of_another_line_runs_beside_it(self):
        with self.line_lock(2).open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apply", self.sandbox.commands())


class TestCloudflareAnswer(ZoneCase):
    def assert_failed_cleanly(self, result):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("failed: Cloudflare GET", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn(ZONE_TOKEN, result.stderr)

    def test_a_malformed_answer_fails_a_create_before_the_apply(self):
        for name, answer in (
            ("no JSON", b"<html>"),
            ("no result", b'{"success": true}'),
            ("a list", b"[]"),
            ("a null result", b'{"success": true, "result": null}'),
            ("an object result", b'{"success": true, "result": {}}'),
            ("no success", b'{"success": false, "result": []}'),
            ("success missing", b'{"result": []}'),
        ):
            with self.subTest(answer=name):
                self.sandbox.platform.cloudflare_answer = answer
                result = self.sandbox.run("zone", **CREATE)
                self.assert_failed_cleanly(result)
                self.assertNotIn("apply", self.sandbox.commands())

    def test_a_malformed_zone_answer_fails_a_show(self):
        self.hold()
        for name, answer in (
            ("no status", b'{"success": true, "result": {}}'),
            ("a list result", b'{"success": true, "result": []}'),
            ("no success", b'{"success": false, "result": {}}'),
            (
                "no success with a whole zone",
                json.dumps(
                    {
                        "success": False,
                        "result": {"status": "active", "name_servers": NAME_SERVERS},
                    }
                ).encode(),
            ),
        ):
            with self.subTest(answer=name):
                self.sandbox.platform.cloudflare_answer = answer
                self.assert_failed_cleanly(self.sandbox.run("zone", **SHOW))

    def test_negative_control_an_empty_zone_list_lets_a_create_apply(self):
        self.sandbox.platform.cloudflare_answer = b'{"success": true, "result": []}'
        result = self.sandbox.run("zone", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apply", self.sandbox.commands())


if __name__ == "__main__":
    unittest.main()
