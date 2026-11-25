from __future__ import annotations

import fcntl
import importlib
import json
import os
import socket
import unittest
from pathlib import Path

from utils.cache.files import read_text

from .provision._fake_provision import (
    CHILD_TOKEN,
    CREDENTIALS,
    CUSTOMER_TOKEN,
    FILES,
    KEYSTONE_SUBJECT,
    LOCK_ID,
    OUTPUTS,
    ROUTE53_KEYS,
    SCS_CREDENTIAL_ID,
    SCS_CREDENTIAL_SECRET,
    SNAPSHOT_RECORD,
    STATE_KEYS,
    TOKEN,
    WORKSPACE,
    ZONE,
    FakeKeystone,
    Sandbox,
    keystone_record,
    keystone_token,
    secret_parts,
)

REFUSED = (
    "main.tf",
    "nested/extra.tf.json",
    "a.tofu",
    "b.tofu.json",
    ".terraformrc",
    ".tofurc",
)
STATE_OBJECT = f"{WORKSPACE}-state/SO-2026/1.tfstate"
RECORD_OBJECT = f"{WORKSPACE}-state/SO-2026/1.provision.json"
CUSTOMER_PATH = f"tenant/data/{WORKSPACE}-provision/providers/hetzner"
SCS_CUSTOMER_PATH = f"tenant/data/{WORKSPACE}-provision/providers/scs"
SCS_REGION = "RegionCatalog"
KEPT_OBJECTS = (
    f"{WORKSPACE}-state/SO-2026/2.tfstate",
    f"{WORKSPACE}-state/SO-2026/1.dns.tfstate",
)
POLICIES = importlib.import_module(
    "tests.unit.python.roles.web-app-openbao.test_policies"
)
FOREIGN_DNS_TOKEN = "platform/data/provision/cloudflare/example.net"
SOURCES = ("secrets", "workspace_secrets")
BROKER = "broker"
TRANSIT_CHILD = {
    "role": f"{WORKSPACE}-transit-child",
    "policies": [f"{WORKSPACE}-transit"],
    "ttl": "7200s",
    "renewable": False,
    "no_default_policy": True,
}
DNS_CHILD = TRANSIT_CHILD | {
    "role": f"{WORKSPACE}-dns-child",
    "policies": [f"{WORKSPACE}-dns"],
}
ZONE_GRANT = (
    'path "{{ OPENBAO_PLATFORM_MOUNT }}/data/provision/cloudflare/'
    '{{ workspace_dns.zone }}" { capabilities = ["read"] }'
)
BROKER_FILE = "modules/dns/broker.json"
SESSION_BROKER = "        broker = reach.get(BROKER)\n"
WRAPPER_EXEC = "exec env -u SEMAPHORE_JWT python3"
UNDUMPABLE_CALL = "    undumpable()\n"
MAIN_BLOCK = 'if __name__ == "__main__":'
AFTER_UNDUMPABLE = ("task_token(TASK_JWT_FD)", "main(sys.argv")
KEPT_TOKEN_REFUSAL = "    if TASK_JWT in os.environ:\n"
DIRECT_TOFU_AT = "    command = arguments[0]\n"
DIRECT_TOFU = (
    DIRECT_TOFU_AT + "    import subprocess\n"
    "    done = subprocess.run(\n"
    '        ["tofu", *arguments], cwd=task, text=True,\n'
    "        env={**environment, **{k: v for k, v in __import__('os').environ.items()"
    " if k.startswith('FAKE_TOFU_')}},\n"
    "        stdout=subprocess.PIPE if capture else None,\n"
    "    )\n"
    '    return done.stdout or ""\n'
)


def dump_order_findings(text):
    """Args:
        text: the source of ``provision.py``.

    Returns:
        One finding per step of the entry point that reads the task token or
        starts the run, and so the login, before the process is undumpable.
    """
    block = text[text.index(MAIN_BLOCK) :]
    if UNDUMPABLE_CALL not in block:
        return ["the entry point never calls undumpable()"]
    first = block.index(UNDUMPABLE_CALL)
    return [
        f"{step} runs before undumpable()"
        for step in AFTER_UNDUMPABLE
        if block.index(step) < first
    ]


def descent_findings(calls):
    """Args:
        calls: the recorded ``tofu`` calls of a run.

    Returns:
        One finding per call whose ``tofu`` descends from ``provision.py``,
        the process that opened its sandbox: such a ``tofu``, and every
        process between them, runs as the runner's uid, outside the sandbox.
    """
    return [
        f"tofu {call['argv'][0]} descends from provision.py"
        for call in calls
        if call["requester"] in call["ancestors"]
    ]


def logins_of(provider):
    return [f"{WORKSPACE}-provision-{provider}"]


def concrete(path):
    return path.format(workspace=WORKSPACE, zone=ZONE, host="target")


STATE_PATH = concrete(CREDENTIALS["state"]["path"])
BROKERED_TOKENS = {
    concrete(entry["path"]) for entry in CREDENTIALS["dns"].values() if BROKER in entry
}


def provider_reads(provider, kinds):
    """Args:
        provider: a provider of ``credentials.json``.
        kinds: the secret lists of the provider whose paths count.

    Returns:
        Every OpenBao path the run of a line on that provider reads for it.
    """
    spec = CREDENTIALS["providers"][provider]
    return {concrete(secret["path"]) for kind in kinds for secret in spec.get(kind, [])}


def run_reads():
    """Returns:
    The paths every provision run reads whatever its provider: the state
    keys, the snapshot record and the DNS credential of each flavor the run
    reads itself; the zone token of a flavor with a ``broker`` only the DNS
    broker reads.
    """
    dns = {
        concrete(entry["path"])
        for entry in CREDENTIALS["dns"].values()
        if BROKER not in entry
    }
    return {concrete(CREDENTIALS["state"]["path"]), SNAPSHOT_RECORD, *dns}


def tofu_reach(provider, granted, source=None):
    """Args:
        provider: the provider of the line.
        granted: the store's switch ``WORKSPACE_PLATFORM_TOKENS``.
        source: a policy template text that replaces the role's own file.

    Returns:
        Every path of ``credentials.json``, of the snapshot record and of a
        foreign zone's DNS token that the token of the line's provider role
        reads, the brokered zone tokens among them.
    """
    every = (
        run_reads()
        | BROKERED_TOKENS
        | {concrete(CREDENTIALS["zone"]["path"]), FOREIGN_DNS_TOKEN}
        | {
            path
            for name in CREDENTIALS["providers"]
            for path in provider_reads(name, SOURCES)
        }
    )
    grants = POLICIES.parse(
        POLICIES.provision_policy(
            WORKSPACE.removeprefix("ws-"), provider, granted, ZONE, source
        )
    )
    return {path for path in every if "read" in POLICIES.effective(grants, path)}


def key_findings(call, keys, allowed_aws):
    """Args:
        call: one recorded ``tofu`` call.
        keys: the backend keys that must not leave the backend file.
        allowed_aws: the only ``AWS_*`` variables the call may carry.

    Returns:
        One finding per key on argv or in the environment.
    """
    findings = [
        f"argv carries {name}"
        for name, value in keys.items()
        for argument in call["argv"]
        if value in argument
    ]
    findings += [
        f"{variable} carries {name}"
        for name, value in keys.items()
        for variable, text in call["env"].items()
        if value in text
    ]
    aws = {
        name: value for name, value in call["env"].items() if name.startswith("AWS_")
    }
    if aws != allowed_aws:
        findings.append(f"AWS_* is {sorted(aws)}, expected {sorted(allowed_aws)}")
    return findings


class ProvisionCase(unittest.TestCase):
    flavor = "knot"

    def setUp(self):
        self.sandbox = Sandbox(self.flavor)
        self.addCleanup(self.sandbox.close)
        self.sandbox.tfvars()

    def assert_refused(self, result, *words):
        self.assertEqual(result.returncode, 2, result.stderr)
        for word in words:
            self.assertIn(word, result.stderr)
        self.assertEqual(self.sandbox.calls(), [])

    def call(self, command):
        return next(c for c in self.sandbox.calls() if c["argv"][0] == command)

    def provision_record(self):
        path = self.sandbox.catalogs / "incus.json"
        catalog = json.loads(path.read_text())  # nocheck: cache-read tempdir
        return json.dumps({"provider": "incus", "catalog": catalog}).encode()

    def provisioned(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.set_plan({"state": ["hcloud_server.server"], "outputs": {}})
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.sandbox.calls()


class TestCheckout(ProvisionCase):
    def test_provision_refuses_infrastructure_code_in_the_checkout(self):
        for relative in REFUSED:
            with self.subTest(file=relative):
                path = self.sandbox.checkout / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("planted", encoding="utf-8")
                self.assert_refused(self.sandbox.run("provision-incus"), relative)
                path.unlink()
        clean = self.sandbox.run("provision-incus")
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(self.sandbox.commands(), ["init", "apply", "output"])

    def test_destroy_refuses_infrastructure_code_in_the_checkout(self):
        (self.sandbox.checkout / "main.tf").write_text("planted", encoding="utf-8")
        self.assert_refused(self.sandbox.run("destroy-incus"), "main.tf")

    def test_provision_refuses_each_malformed_tfvars(self):
        cases = {
            "unknown key": {"image": "debian"},
            "wrong type": {"size": 1},
            "unknown size": {"size": "huge"},
            "unknown region": {"region": "mars"},
        }
        for case, values in cases.items():
            with self.subTest(case=case):
                self.sandbox.tfvars(values)
                self.assert_refused(self.sandbox.run("provision-incus"))
        self.sandbox.tfvars().write_text('name = "SO-2026-1"\n', encoding="utf-8")
        self.assert_refused(self.sandbox.run("provision-incus"), "is no JSON document")

    def test_a_tfvars_file_of_another_line_is_refused(self):
        self.sandbox.tfvars().unlink()
        self.assert_refused(
            self.sandbox.run("provision-incus"), "provision/SO-2026-1.tfvars.json"
        )
        self.sandbox.tfvars({"name": "SO-2026-2"})
        self.assert_refused(self.sandbox.run("provision-incus"), "not 'SO-2026-1'")

    def test_provision_reads_the_mounted_catalog_only(self):
        planted = {"cloud": {"sizes": {"huge": {}}, "regions": {"mars": {}}}}
        image_root = self.sandbox.core / "opentofu" / "roots" / "incus"
        for directory in (self.sandbox.checkout, image_root):
            (directory / "catalog.json").write_text(json.dumps(planted))
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        mounted = self.sandbox.catalogs / "incus.json"
        text = mounted.read_text()  # nocheck: cache-read tempdir
        self.assertEqual(self.call("apply")["texts"]["catalog.json"], text)
        self.sandbox.tfvars({"size": "huge", "region": "mars"})
        self.assert_refused(self.sandbox.run("provision-incus"), "region 'mars'")
        self.sandbox.tfvars()
        (self.sandbox.catalogs / "incus.json").write_text("{}")
        self.assert_refused(
            self.sandbox.run("provision-incus"),
            "no catalog offers region 'default'",
            "incus",
        )

    def test_provision_runs_the_image_module_with_a_clean_tf_env(self):
        result = self.sandbox.run(
            "provision-incus",
            TF_CLI_ARGS="-destroy",
            TF_CLI_ARGS_apply="-refresh=false",
            TF_VAR_name="injected",
            TF_LOG="TRACE",
            INCUS_ADDR="https://attacker.example.org",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        root = FILES / "opentofu"
        for call in self.sandbox.calls():
            env, cwd = call["env"], Path(call["cwd"])
            self.assertFalse(
                any(n.startswith(("TF_CLI_ARGS", "TF_VAR_", "TF_LOG")) for n in env)
            )
            self.assertNotIn("SEMAPHORE_JWT", env)
            self.assertEqual(env["INCUS_ADDR"], "https://incus.example.org:8443")
            self.assertEqual(
                env["TF_CLI_CONFIG_FILE"],
                str(self.sandbox.core / "opentofu" / "tofurc"),
            )
            self.assertTrue(cwd.is_relative_to(self.sandbox.spawner.root))
            self.assertNotEqual(cwd, self.sandbox.checkout)
            texts = call["texts"]
            for name in ("main.tf.json", "variables.tf.json", "outputs.tf.json"):
                self.assertEqual(
                    texts[name], read_text(str(root / "roots" / "incus" / name))
                )
            self.assertEqual(
                texts["modules/dns/main.tf.json"],
                read_text(str(root / "modules" / "dns-knot" / "main.tf.json")),
            )
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1])["fqdn"],
            f"app.{WORKSPACE}.{ZONE}",
        )

    def test_provision_takes_the_provider_settings_from_openbao(self):
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.call("apply")
        env = call["env"]
        self.assertEqual(env["INCUS_REMOTE"], "target")
        credentials = Path(env["INCUS_CONF"])
        self.assertTrue(credentials.is_relative_to(Path(call["cwd"])))
        self.assertEqual(call["texts"]["credentials/client.key"], "CLIENT-KEY")
        self.assertEqual(
            call["texts"]["credentials/servercerts/target.crt"], "SERVER-CERT"
        )
        self.assertEqual(env["BAO_TOKEN"], CHILD_TOKEN)
        self.assertEqual(env["DNS_UPDATE_SERVER"], "127.0.0.1")
        encryption = json.loads(env["TF_ENCRYPTION"])
        self.assertEqual(
            encryption["key_provider"]["openbao"]["workspace"]["key_name"],
            f"{WORKSPACE}-provision",
        )
        self.assertIs(encryption["state"]["enforced"], True)
        self.assertIs(encryption["plan"]["enforced"], True)


class TestState(ProvisionCase):
    def test_the_state_key_is_sales_order_and_line(self):
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        init = self.call("init")
        backend = init["backend"]["text"]
        self.assertIn(f'bucket = "{WORKSPACE}-state"\n', backend)
        self.assertIn('key = "SO-2026/1.tfstate"\n', backend)
        self.assertNotIn("987654", backend)
        versions = json.loads(init["texts"]["versions.tf.json"])
        self.assertIs(versions["terraform"]["backend"]["s3"]["use_lockfile"], True)

    def test_each_provision_template_refuses_a_malformed_order_line(self):
        cases = {
            "SALES_ORDER": ("1SO", "S" * 57, "SO_2026", ""),
            "LINE": ("1-2", "1234567", "x", "", "0", "007"),
        }
        for script in ("provision-incus", "destroy-incus", "unlock"):
            for name, values in cases.items():
                for value in values:
                    with self.subTest(script=script, name=name, value=value):
                        result = self.sandbox.run(script, **{name: value})
                        self.assert_refused(result, name)

    def test_provision_writes_workspace_json_from_the_environment(self):
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.call("init")["texts"]["workspace.json"]),
            {"workspace": WORKSPACE, "dns": {"zone": ZONE, "zone_id": ""}},
        )
        cases = {
            "WORKSPACE": (None, "workspace-1", "ws-UPPER"),
            "WORKSPACE_DNS_ZONE": ("Not A Zone", "-bad.example.org"),
            "WORKSPACE_DNS_ZONE_ID": ("Z123",),
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    self.assert_refused(
                        self.sandbox.run("provision-incus", **{name: value}), name
                    )
        for key in ("zone", "workspace"):
            with self.subTest(key=key):
                self.sandbox.tfvars({key: "chosen-by-the-checkout"})
                self.assert_refused(
                    self.sandbox.run("provision-incus"), key, "is not a known key"
                )

    def test_the_task_directory_is_removed_on_every_exit(self):
        for fail, code in ((None, 0), ("apply", 1), ("init", 1)):
            with self.subTest(fail=fail):
                self.sandbox.log.unlink(missing_ok=True)
                self.sandbox.set_plan({"state": [], "outputs": {}, "fail": fail})
                result = self.sandbox.run("provision-incus")
                self.assertEqual(result.returncode, code, result.stderr)
                for call in self.sandbox.calls():
                    task = Path(call["cwd"])
                    self.assertFalse(task.exists())
                    self.assertFalse((task / "backend.tfbackend").exists())
                    self.assertFalse((task / ".terraform").exists())
                self.assertEqual(list(self.sandbox.spawner.root.iterdir()), [])


class TestBackendKeys(ProvisionCase):
    def test_backend_keys_come_from_a_private_file(self):
        result = self.sandbox.run(
            "provision-incus", AWS_ACCESS_KEY_ID="planted", AWS_PROFILE="planted"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in self.sandbox.calls():
            self.assertEqual(key_findings(call, STATE_KEYS, {}), [])
        init = self.call("init")
        configs = [a for a in init["argv"] if a.startswith("-backend-config")]
        self.assertEqual(len(configs), 1)
        path = Path(configs[0].split("=", 1)[1])
        self.assertTrue(path.is_relative_to(Path(init["cwd"])))
        self.assertEqual(init["backend"]["mode"], 0o640)
        for name, value in STATE_KEYS.items():
            self.assertIn(f'{name} = "{value}"\n', init["backend"]["text"])

    def test_negative_control_a_key_on_argv_fails(self):
        call = {
            "argv": ["init", f"-backend-config=access_key={STATE_KEYS['access_key']}"],
            "env": {},
        }
        self.assertEqual(
            key_findings(call, STATE_KEYS, {}), ["argv carries access_key"]
        )

    def test_negative_control_a_key_in_aws_access_key_id_fails(self):
        call = {
            "argv": ["init"],
            "env": {"AWS_ACCESS_KEY_ID": STATE_KEYS["access_key"]},
        }
        self.assertEqual(len(key_findings(call, STATE_KEYS, {})), 2)


class TestRoute53Keys(ProvisionCase):
    flavor = "route53"

    def test_route53_sets_only_the_iam_user_keys(self):
        allowed = {
            "AWS_ACCESS_KEY_ID": ROUTE53_KEYS["access_key"],
            "AWS_SECRET_ACCESS_KEY": ROUTE53_KEYS["secret_key"],
        }
        for call in self.provisioned():
            self.assertEqual(key_findings(call, STATE_KEYS, allowed), [])


class TestTheBrokeredZoneToken(ProvisionCase):
    flavor = "cloudflare"

    def zone_token_findings(self, calls):
        """Args:
            calls: the recorded ``tofu`` calls of a run.

        Returns:
            One finding per call that carries the zone token of the brokered
            flavor in its environment or on argv, and one per read of that
            token by the run.
        """
        (path,) = BROKERED_TOKENS
        token = self.sandbox.platform.secrets[path]["token"]
        findings = [
            f"tofu {call['argv'][0]} carries the zone token in {name}"
            for call in calls
            for name, value in call["env"].items()
            if token in value
        ]
        findings += [
            f"tofu {call['argv'][0]} carries the zone token on argv"
            for call in calls
            if any(token in argument for argument in call["argv"])
        ]
        findings += [
            f"the run read {read}"
            for read in self.sandbox.platform.reads
            if read in BROKERED_TOKENS
        ]
        return findings

    def test_tofu_holds_the_dns_child_and_reaches_the_broker(self):
        calls = self.provisioned()
        self.assertEqual(self.zone_token_findings(calls), [])
        tokens = {call["env"].get("CLOUDFLARE_API_TOKEN") for call in calls}
        self.assertEqual(tokens, {CHILD_TOKEN})
        self.assertEqual(self.sandbox.platform.children, [DNS_CHILD, TRANSIT_CHILD])
        broker = CREDENTIALS["dns"][self.flavor][BROKER]
        expected = f"http://{broker['listen']}:{broker['port']}{broker['base']}"
        for call in calls:
            with self.subTest(command=call["argv"][0]):
                staged = json.loads(call["texts"][BROKER_FILE])
                self.assertEqual(staged, {"base_url": expected})

    def test_negative_control_a_session_reading_the_zone_token_is_found(self):
        path = self.sandbox.core / "python" / "provision" / "session.py"
        text = read_text(str(FILES / "python" / "provision" / "session.py"))
        planted = text.replace(SESSION_BROKER, "        broker = None\n")
        self.assertNotEqual(planted, text)
        path.write_text(planted)
        findings = self.zone_token_findings(self.provisioned())
        (read,) = BROKERED_TOKENS
        self.assertIn(f"the run read {read}", findings)
        self.assertTrue(
            any(finding.endswith("CLOUDFLARE_API_TOKEN") for finding in findings)
        )


class TestTakenName(ProvisionCase):
    def test_provision_refuses_a_name_that_holds_an_address(self):
        self.sandbox.dns.records[(f"app.{WORKSPACE}.{ZONE}", 1)] = [
            socket.inet_aton("198.51.100.7")
        ]
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("already holds an A, AAAA or CNAME record", result.stderr)
        self.assertEqual(self.sandbox.commands(), ["init"])
        self.assertTrue(all(rd == 0 for _, _, rd in self.sandbox.dns.questions))

    def test_an_existing_server_state_skips_the_check(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.set_plan(
            {"state": ["module.dns.dns_a_record_set.record[0]"], "outputs": {}}
        )
        self.sandbox.dns.records[(f"app.{WORKSPACE}.{ZONE}", 1)] = [
            socket.inet_aton("192.0.2.10")
        ]
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sandbox.commands(), ["init", "state", "apply", "output"])
        self.assertEqual(self.sandbox.dns.questions, [])


class TestUnlock(ProvisionCase):
    def test_unlock_force_unlocks_with_the_id_of_the_lock_object(self):
        self.sandbox.platform.objects[f"{STATE_OBJECT}.tflock"] = json.dumps(
            {"ID": LOCK_ID, "Who": "runner@provision"}
        ).encode()
        result = self.sandbox.run("unlock")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.call("force-unlock")["argv"], ["force-unlock", "-force", LOCK_ID]
        )
        self.assertIn(
            'key = "SO-2026/1.tfstate"\n', self.call("init")["backend"]["text"]
        )

    def test_unlock_without_a_lock_changes_nothing(self):
        result = self.sandbox.run("unlock")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("holds no lock", result.stdout)
        self.assertEqual(self.sandbox.commands(), ["init"])

    def test_unlock_refuses_while_a_provision_of_the_workspace_runs(self):
        locks = self.sandbox.tmp / "provision-locks"
        locks.mkdir(mode=0o700)
        with (locks / f"{WORKSPACE}.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            result = self.sandbox.run("unlock")
        self.assert_refused(result, "a provision or destroy task", WORKSPACE)


class TestKeySnapshot(ProvisionCase):
    def assert_no_state_write(self, script, *words):
        result = self.sandbox.run(script)
        self.assertEqual(result.returncode, 2, result.stderr)
        for word in (SNAPSHOT_RECORD, *words):
            self.assertIn(word, result.stderr)
        self.assertEqual(self.sandbox.commands(), ["init"])

    def test_a_missing_snapshot_record_refuses_before_any_state_write(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        del self.sandbox.platform.secrets[SNAPSHOT_RECORD]
        for script in ("provision-incus", "destroy-incus"):
            with self.subTest(script=script):
                self.assert_no_state_write(script, "has no backup")

    def test_a_snapshot_older_than_the_key_refuses_before_any_state_write(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.platform.secrets[SNAPSHOT_RECORD] = {
            "key_created_at": "1763000005",
            "snapshot_at": "1763000000",
        }
        for script in ("provision-incus", "destroy-incus"):
            with self.subTest(script=script):
                self.assert_no_state_write(script, "predates the transit key")

    def test_negative_control_without_the_snapshot_check_a_younger_key_writes(self):
        self.sandbox.platform.secrets[SNAPSHOT_RECORD] = {
            "key_created_at": "1763000005",
            "snapshot_at": "1763000000",
        }
        text = read_text(str(FILES / "python" / "provision" / "session.py"))
        planted = text.replace(
            "        require_snapshot(self.bao, self.workspace)\n        if self.empty():",
            "        if self.empty():",
        )
        self.assertNotEqual(planted, text)
        (self.sandbox.core / "python" / "provision" / "session.py").write_text(planted)
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apply", self.sandbox.commands())

    def test_a_malformed_snapshot_record_refuses(self):
        self.sandbox.platform.secrets[SNAPSHOT_RECORD] = {
            "key_created_at": "yesterday",
            "snapshot_at": "1763000000",
        }
        self.assert_no_state_write("provision-incus", "has no backup")

    def test_a_snapshot_after_the_key_admits_the_write(self):
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(SNAPSHOT_RECORD, self.sandbox.platform.reads)
        self.assertIn("apply", self.sandbox.commands())

    def test_unlock_writes_no_state_and_needs_no_snapshot(self):
        del self.sandbox.platform.secrets[SNAPSHOT_RECORD]
        result = self.sandbox.run("unlock")
        self.assertEqual(result.returncode, 0, result.stderr)


class TestArguments(ProvisionCase):
    def test_each_script_refuses_an_extra_argument(self):
        for script in ("provision-incus", "destroy-incus", "unlock", "dns"):
            with self.subTest(script=script):
                self.assert_refused(
                    self.sandbox.run(script, "-destroy"),
                    "unexpected argument '-destroy'",
                )

    def test_provision_and_destroy_refuse_a_missing_or_unknown_provider(self):
        for template in ("provision", "destroy", "provision-aws", "destroy-aws"):
            with self.subTest(template=template):
                self.assert_refused(self.sandbox.run(template), "pins no provider")
                self.assertEqual(self.sandbox.platform.logins, [])

    def test_a_provision_of_a_line_on_another_provider_is_refused_before_login(self):
        self.assert_refused(
            self.sandbox.run("provision-hetzner"),
            "line SO-2026-1 is on incus, but this template pins hetzner",
        )
        self.assertEqual(self.sandbox.platform.logins, [])

    def test_negative_control_without_the_pin_a_foreign_line_reaches_apply(self):
        text = read_text(str(FILES / "python" / "provision.py"))
        planted = text.replace(
            '        require_pinned(pinned, selected[0], values["name"])\n', ""
        )
        self.assertNotEqual(planted, text)
        (self.sandbox.core / "python" / "provision.py").write_text(planted)
        result = self.sandbox.run("provision-hetzner")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apply", self.sandbox.commands())

    def test_a_destroy_of_a_line_recorded_on_another_provider_is_refused(self):
        objects = self.sandbox.platform.objects
        objects[STATE_OBJECT] = b"encrypted"
        objects[RECORD_OBJECT] = self.provision_record()
        self.assert_refused(
            self.sandbox.run("destroy-hetzner"),
            "line SO-2026-1 is on incus, but this template pins hetzner",
        )
        self.assertEqual(
            self.sandbox.platform.logins, [f"{WORKSPACE}-provision-hetzner"]
        )
        self.assertEqual(self.sandbox.platform.reads, [STATE_PATH])
        self.assertEqual(self.sandbox.platform.children, [])
        self.assertEqual(self.sandbox.platform.revoked, [TOKEN])
        self.assertIn(STATE_OBJECT, objects)
        self.assertIn(RECORD_OBJECT, objects)

    def test_negative_control_a_session_opened_before_the_pin_reads_the_dns_secret(
        self,
    ):
        text = read_text(str(FILES / "python" / "provision.py"))
        held = "    ):\n        if selected is None and session.holds_nothing"
        planted = text.replace(
            held,
            "    ):\n        session.open(reach)\n"
            "        if selected is None and session.holds_nothing",
        )
        self.assertNotEqual(planted, text)
        (self.sandbox.core / "python" / "provision.py").write_text(planted)
        objects = self.sandbox.platform.objects
        objects[STATE_OBJECT] = b"encrypted"
        objects[RECORD_OBJECT] = self.provision_record()
        self.assert_refused(self.sandbox.run("destroy-hetzner"), "pins hetzner")
        self.assertNotEqual(self.sandbox.platform.reads, [STATE_PATH])
        self.assertNotEqual(self.sandbox.platform.children, [])

    def test_destroy_destroys_with_the_checkout_values(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        result = self.sandbox.run("destroy-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        destroy = self.call("destroy")
        self.assertEqual(
            destroy["argv"],
            [
                "destroy",
                "-auto-approve",
                "-input=false",
                "-var-file=values.tfvars.json",
            ],
        )
        self.assertEqual(
            json.loads(destroy["texts"]["values.tfvars.json"])["name"], "SO-2026-1"
        )


class TestProviderToken(ProvisionCase):
    def setUp(self):
        super().setUp()
        sizes = {"cx22": {"server_type": "cx22"}}
        self.sandbox.write_catalogs(
            {
                "hetzner": {"cloud": {"sizes": sizes, "regions": {"fsn1": {}}}},
                "scs": {"cloud": {"sizes": sizes, "regions": {"scs1": {}}}},
            }
        )
        self.sandbox.tfvars({"size": "cx22", "region": "fsn1"})

    def apply_env(self, token):
        result = self.sandbox.run("provision-hetzner", PROVIDER_TOKEN=token)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(CUSTOMER_TOKEN, result.stdout + result.stderr)
        for call in self.sandbox.calls():
            self.assertFalse(any(CUSTOMER_TOKEN in arg for arg in call["argv"]))
        return self.call("apply")["env"]

    def test_platform_takes_the_platform_token_only(self):
        env = self.apply_env("platform")
        self.assertEqual(env["HCLOUD_TOKEN"], "hcloud-platform-token")
        self.assertNotIn(CUSTOMER_PATH, self.sandbox.platform.reads)

    def test_a_provision_run_logs_in_with_its_provider_role_only(self):
        self.apply_env("platform")
        self.assertEqual(self.sandbox.platform.logins, logins_of("hetzner"))

    def test_workspace_takes_the_customer_token_only(self):
        env = self.apply_env("workspace")
        self.assertEqual(env["HCLOUD_TOKEN"], CUSTOMER_TOKEN)
        self.assertNotIn("platform/data/provision/hetzner", self.sandbox.platform.reads)

    def test_negative_control_a_missing_customer_token_refuses_before_tofu(self):
        secrets = self.sandbox.platform.secrets
        for planted in (None, {}, {"token": ""}, {"other": "x"}):
            with self.subTest(planted=planted):
                secrets.pop(CUSTOMER_PATH, None)
                if planted is not None:
                    secrets[CUSTOMER_PATH] = planted
                self.assert_refused(
                    self.sandbox.run("provision-hetzner", PROVIDER_TOKEN="workspace"),
                    CUSTOMER_PATH,
                    "holds no token",
                )

    def test_destroy_takes_the_same_token_as_provision(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        result = self.sandbox.run("destroy-hetzner", PROVIDER_TOKEN="workspace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call("destroy")["env"]["HCLOUD_TOKEN"], CUSTOMER_TOKEN)

    def test_a_missing_or_unknown_provider_token_is_refused(self):
        for value in (None, "", "customer", "Platform"):
            with self.subTest(value=value):
                self.assert_refused(
                    self.sandbox.run("provision-hetzner", PROVIDER_TOKEN=value),
                    "PROVIDER_TOKEN",
                )

    def scs_line(self, record):
        """Args:
            record: the ``application_credential`` the fake Keystone holds.

        Returns:
            The fake Keystone of the line's catalog region.
        """
        keystone = FakeKeystone(keystone_token(), record)
        self.addCleanup(keystone.stop)
        region = {"auth_url": keystone.auth_url, "region": SCS_REGION, "network": "n"}
        sizes = {"m1": {"flavor": "SCS-1V-2"}}
        self.sandbox.write_catalogs(
            {"scs": {"cloud": {"sizes": sizes, "regions": {"scs1": region}}}}
        )
        self.sandbox.tfvars({"size": "m1", "region": "scs1"})
        self.sandbox.platform.secrets[SCS_CUSTOMER_PATH] = {
            "application_credential_id": SCS_CREDENTIAL_ID,
            "application_credential_secret": SCS_CREDENTIAL_SECRET,
        }
        return keystone

    def s3_methods(self):
        return [method for method, _ in self.sandbox.platform.s3_requests]

    def test_a_bad_scs_credential_refuses_before_any_write(self):
        keystone = self.scs_line(keystone_record() | {"unrestricted": True})
        result = self.sandbox.run("provision-scs", PROVIDER_TOKEN="workspace")
        self.assert_refused(
            result, "refused: the application credential is unrestricted"
        )
        self.assertNotIn("PUT", self.s3_methods())
        self.assertEqual(
            secret_parts(
                result.stdout + result.stderr, SCS_CREDENTIAL_SECRET, KEYSTONE_SUBJECT
            ),
            [],
        )
        self.assertEqual(keystone.revoked, 1)

    def test_negative_control_a_good_scs_credential_writes_and_applies(self):
        keystone = self.scs_line(keystone_record())
        result = self.sandbox.run("provision-scs", PROVIDER_TOKEN="workspace")
        self.assertEqual(result.returncode, 0, result.stderr)
        env = self.call("apply")["env"]
        self.assertEqual(env["OS_AUTH_URL"], keystone.auth_url)
        self.assertEqual(env["OS_REGION_NAME"], SCS_REGION)
        self.assertEqual(env["OS_APPLICATION_CREDENTIAL_ID"], SCS_CREDENTIAL_ID)
        self.assertIn("PUT", self.s3_methods())
        self.assertEqual(keystone.revoked, 1)

    def test_a_provider_without_customer_tokens_refuses_workspace(self):
        self.sandbox.tfvars({"size": "demo", "region": "default"})
        self.assert_refused(
            self.sandbox.run("provision-incus", PROVIDER_TOKEN="workspace"),
            "PROVIDER_TOKEN",
            "incus takes no customer token",
        )


class TestTheTofuToken(ProvisionCase):
    def test_the_tofu_token_reaches_the_line_provider_only(self):
        for provider in CREDENTIALS["providers"]:
            with self.subTest(provider=provider):
                self.assertEqual(
                    tofu_reach(provider, True),
                    run_reads() | provider_reads(provider, SOURCES),
                )
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sandbox.platform.logins, logins_of("incus"))

    def test_without_the_store_switch_the_token_reads_the_customer_token_only(self):
        for provider in CREDENTIALS["providers"]:
            with self.subTest(provider=provider):
                self.assertEqual(
                    tofu_reach(provider, False),
                    run_reads() | provider_reads(provider, ("workspace_secrets",)),
                )

    def test_negative_control_a_planted_wildcard_reaches_other_providers(self):
        source = (
            read_text(str(POLICIES.PROVISION_POLICY)) + "\n" + POLICIES.WILDCARD + "\n"
        )
        reach = tofu_reach("incus", True, source)
        self.assertNotEqual(reach, run_reads() | provider_reads("incus", SOURCES))
        self.assertIn("platform/data/provision/hetzner", reach)

    def test_no_provision_token_reads_a_brokered_zone_token(self):
        self.assertTrue(BROKERED_TOKENS)
        for provider in CREDENTIALS["providers"]:
            for granted in (True, False):
                with self.subTest(provider=provider, granted=granted):
                    reach = tofu_reach(provider, granted)
                    self.assertEqual(reach & BROKERED_TOKENS, set())

    def test_negative_control_a_planted_zone_grant_reaches_the_zone_token(self):
        source = read_text(str(POLICIES.PROVISION_POLICY)) + "\n" + ZONE_GRANT + "\n"
        reach = tofu_reach("incus", True, source)
        self.assertEqual(reach & BROKERED_TOKENS, BROKERED_TOKENS)

    def tofu_tokens(self):
        return {call["env"].get("BAO_TOKEN") for call in self.sandbox.calls()}

    def test_tofu_holds_a_transit_child_token_never_the_role_token(self):
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tofu_tokens(), {CHILD_TOKEN})
        self.assertEqual(self.sandbox.platform.children, [TRANSIT_CHILD])

    def test_negative_control_a_session_handing_tofu_the_role_token_fails(self):
        path = self.sandbox.core / "python" / "provision" / "session.py"
        text = read_text(str(FILES / "python" / "provision" / "session.py"))
        planted = text.replace('"BAO_TOKEN": transit,', '"BAO_TOKEN": self.bao.token,')
        self.assertNotEqual(planted, text)
        path.write_text(planted)
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tofu_tokens(), {TOKEN})

    def plant(self, relative, *replacements):
        """Args:
        relative: a file below ``files`` of the role, replaced in the
            sandbox.
        replacements: ``(old, new)`` pairs, each of which must change it.
        """
        text = read_text(str(FILES / relative))
        for old, new in replacements:
            planted = text.replace(old, new)
            self.assertNotEqual(planted, text, old)
            text = planted
        (self.sandbox.core / relative).write_text(text)

    def plant_dumpable(self, *replacements):
        self.plant("python/provision.py", (UNDUMPABLE_CALL, ""), *replacements)

    def runner_environments(self):
        environments = [call["runner_env"] for call in self.sandbox.calls()]
        self.assertTrue(environments)
        return environments

    def refused_destroy_beside_a_failed_revoke(self):
        self.sandbox.platform.revoke_status = 500
        objects = self.sandbox.platform.objects
        objects[STATE_OBJECT] = b"encrypted"
        objects[RECORD_OBJECT] = self.provision_record()
        return self.sandbox.run("destroy-hetzner")

    def test_the_run_revokes_its_role_token_and_with_it_the_child(self):
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sandbox.platform.revoked, [TOKEN])

    def test_negative_control_a_session_without_the_revoke_leaves_the_token(self):
        path = self.sandbox.core / "python" / "provision" / "session.py"
        text = read_text(str(FILES / "python" / "provision" / "session.py"))
        planted = text.replace("        bao.revoke()\n", "        pass\n")
        self.assertNotEqual(planted, text)
        path.write_text(planted)
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sandbox.platform.revoked, [])

    def test_a_failed_revoke_keeps_the_refusal_of_the_run(self):
        self.assert_refused(
            self.refused_destroy_beside_a_failed_revoke(),
            "refused: line SO-2026-1 is on incus, but this template pins hetzner",
            "the revoke of the role token after the run's own error: OpenBao POST "
            "auth/token/revoke-self: HTTP 500",
        )
        self.assertEqual(self.sandbox.platform.revoked, [])

    def test_negative_control_an_unguarded_revoke_replaces_the_refusal(self):
        self.plant(
            "python/provision/session.py",
            ("        revoke_after_failure(bao)\n", "        bao.revoke()\n"),
        )
        result = self.refused_destroy_beside_a_failed_revoke()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("failed: OpenBao POST auth/token/revoke-self", result.stderr)
        self.assertNotIn("pins hetzner", result.stderr)

    def test_the_python_process_is_undumpable_before_the_login(self):
        text = read_text(str(FILES / "python" / "provision.py"))
        self.assertEqual(dump_order_findings(text), [])
        if os.geteuid() == 0:
            self.skipTest("root reads the environ of an undumpable process")
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        environments = self.runner_environments()
        self.assertEqual([e for e in environments if e is not None], [])

    def test_negative_control_a_dumpable_process_is_found(self):
        text = read_text(str(FILES / "python" / "provision.py"))
        held = "    jwt = task_token(TASK_JWT_FD)\n"
        moved = text.replace(UNDUMPABLE_CALL, "").replace(
            held, held + UNDUMPABLE_CALL, 1
        )
        self.assertNotEqual(dump_order_findings(moved), [])
        if os.geteuid() == 0:
            self.skipTest("root reads the environ of a dumpable process too")
        self.plant_dumpable()
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(None, self.runner_environments())

    def test_no_process_of_the_runner_stands_between_provision_and_tofu(self):
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.sandbox.calls()
        self.assertTrue(calls)
        self.assertEqual(descent_findings(calls), [])

    def test_negative_control_a_tofu_started_by_provision_itself_is_found(self):
        self.plant("python/provision/opentofu.py", (DIRECT_TOFU_AT, DIRECT_TOFU))
        result = self.sandbox.run(
            "provision-incus",
            FAKE_TOFU_LOG=str(self.sandbox.log),
            FAKE_TOFU_PLAN=str(self.sandbox.plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            descent_findings(self.sandbox.calls()),
            [
                f"tofu {command} descends from provision.py"
                for command in self.sandbox.commands()
            ],
        )

    def test_the_task_token_never_reaches_the_python_environment(self):
        self.plant_dumpable()
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sandbox.platform.logins, logins_of("incus"))
        for environment in self.runner_environments():
            self.assertIn("WORKSPACE", environment)
            self.assertNotIn("SEMAPHORE_JWT", environment)
        for script in ("provision", "destroy", "unlock", "dns", "zone"):
            with self.subTest(script=script):
                wrapper = FILES / "shell" / "repository" / f"{script}.sh"
                self.assertIn(WRAPPER_EXEC, read_text(str(wrapper)))

    def test_negative_control_a_token_kept_in_the_environment_is_seen(self):
        self.plant_dumpable((KEPT_TOKEN_REFUSAL, "    if False:\n"))
        self.plant("shell/repository/provision.sh", (WRAPPER_EXEC, "exec python3"))
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        for environment in self.runner_environments():
            self.assertIn("SEMAPHORE_JWT", environment)

    def test_negative_control_a_wrapper_that_keeps_the_token_is_refused(self):
        self.plant("shell/repository/provision.sh", (WRAPPER_EXEC, "exec python3"))
        self.assert_refused(
            self.sandbox.run("provision-incus"), "SEMAPHORE_JWT is in the environment"
        )
        self.assertEqual(self.sandbox.platform.logins, [])

    def test_destroy_takes_the_provider_role_of_the_recorded_line(self):
        objects = self.sandbox.platform.objects
        objects[STATE_OBJECT] = b"encrypted"
        objects[RECORD_OBJECT] = self.provision_record()
        result = self.sandbox.run("destroy-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sandbox.platform.logins, logins_of("incus"))


class TestStateCleanup(ProvisionCase):
    def plant(self):
        objects = self.sandbox.platform.objects
        for key in (STATE_OBJECT, f"{STATE_OBJECT}.tflock", *KEPT_OBJECTS):
            objects[key] = b"encrypted"
        objects[RECORD_OBJECT] = self.provision_record()
        return objects

    def test_destroy_deletes_the_state_and_its_lock_after_tofu_destroy(self):
        objects = self.plant()
        result = self.sandbox.run("destroy-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(objects), sorted(KEPT_OBJECTS))
        deletes = [
            path
            for method, path in self.sandbox.platform.s3_requests
            if method == "DELETE"
        ]
        self.assertEqual(
            deletes,
            [f"/{STATE_OBJECT}", f"/{STATE_OBJECT}.tflock", f"/{RECORD_OBJECT}"],
        )

    def test_negative_control_a_failed_destroy_keeps_the_state(self):
        objects = self.plant()
        self.sandbox.set_plan({"state": [], "outputs": {}, "fail": "destroy"})
        result = self.sandbox.run("destroy-incus")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(STATE_OBJECT, objects)
        self.assertIn(RECORD_OBJECT, objects)
        self.assertNotIn(
            "DELETE", [method for method, _ in self.sandbox.platform.s3_requests]
        )


class TestProvisionRecord(ProvisionCase):
    def provision(self):
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def catalogs(self):
        return {
            path.stem: json.loads(path.read_text())  # nocheck: cache-read tempdir
            for path in self.sandbox.catalogs.glob("*.json")
        }

    def change_catalogs(self, change):
        catalogs = self.catalogs()
        change(catalogs)
        self.sandbox.write_catalogs(catalogs)

    @staticmethod
    def retire_the_region(catalogs):
        regions = catalogs["incus"]["cloud"]["regions"]
        regions["default-2"] = regions.pop("default")

    @staticmethod
    def offer_the_region_twice(catalogs):
        catalogs["hetzner"]["cloud"] = catalogs["incus"]["cloud"]

    def assert_destroyed_with(self, recorded):
        result = self.sandbox.run("destroy-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("live catalogs", result.stdout)
        texts = self.call("destroy")["texts"]
        self.assertEqual(
            json.loads(texts["catalog.json"]), json.loads(recorded)["catalog"]
        )
        self.assertEqual(
            texts["main.tf.json"],
            read_text(str(FILES / "opentofu" / "roots" / "incus" / "main.tf.json")),
        )
        self.assertNotIn(RECORD_OBJECT, self.sandbox.platform.objects)

    def test_provision_records_provider_and_catalog_and_ends_with_the_outputs(self):
        result = self.provision()
        self.assertEqual(
            self.sandbox.platform.objects[RECORD_OBJECT], self.provision_record()
        )
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1]),
            {name: output["value"] for name, output in OUTPUTS.items()},
        )

    def test_a_failed_apply_still_leaves_the_record(self):
        self.sandbox.set_plan({"state": [], "outputs": {}, "fail": "apply"})
        result = self.sandbox.run("provision-incus")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(RECORD_OBJECT, self.sandbox.platform.objects)

    @classmethod
    def switch_to_hetzner(cls, catalogs):
        catalogs["hetzner"]["cloud"] = json.loads(
            json.dumps(catalogs["incus"]["cloud"])
        )
        cls.retire_the_region(catalogs)

    def test_a_provider_switch_is_refused_before_tofu(self):
        self.provision()
        recorded = self.sandbox.platform.objects[RECORD_OBJECT]
        self.change_catalogs(self.switch_to_hetzner)
        self.assert_refused(
            self.sandbox.run("provision-hetzner"),
            "line SO-2026-1 was provisioned with incus",
            "the live catalogs now pick hetzner",
        )
        self.assertEqual(self.sandbox.platform.objects[RECORD_OBJECT], recorded)

    def test_negative_control_without_the_refusal_a_switch_reaches_apply(self):
        self.provision()
        text = read_text(str(FILES / "python" / "provision.py"))
        planted = text.replace("if recorded != selected[0]:", "if not recorded:")
        self.assertNotEqual(planted, text)
        (self.sandbox.core / "python" / "provision.py").write_text(planted)
        self.change_catalogs(self.switch_to_hetzner)
        result = self.sandbox.run("provision-hetzner")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apply", self.sandbox.commands())

    def test_a_re_provision_with_the_same_provider_rewrites_the_record(self):
        self.provision()
        self.change_catalogs(self.retire_the_region)
        self.sandbox.tfvars({"region": "default-2"})
        self.provision()
        self.assertEqual(
            self.sandbox.platform.objects[RECORD_OBJECT], self.provision_record()
        )
        self.assertIn("default-2", self.provision_record().decode())

    def test_destroy_survives_a_retired_region(self):
        self.provision()
        recorded = self.provision_record()
        self.change_catalogs(self.retire_the_region)
        self.assert_destroyed_with(recorded)

    def test_destroy_survives_a_second_provider_offering_the_region(self):
        self.provision()
        recorded = self.provision_record()
        self.change_catalogs(self.offer_the_region_twice)
        self.assert_destroyed_with(recorded)

    def test_negative_control_without_a_record_the_live_catalogs_refuse(self):
        original = self.catalogs()
        cases = (
            (self.retire_the_region, "no catalog offers region 'default'"),
            (self.offer_the_region_twice, "is offered by hetzner, incus"),
        )
        for change, words in cases:
            with self.subTest(change=change.__name__):
                self.sandbox.write_catalogs(original)
                self.provision()
                del self.sandbox.platform.objects[RECORD_OBJECT]
                self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
                self.change_catalogs(change)
                self.assert_refused(self.sandbox.run("destroy-incus"), words)

    def test_destroy_without_a_record_falls_back_to_the_live_catalogs(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        result = self.sandbox.run("destroy-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "SO-2026/1.provision.json is missing, so the destroy takes incus "
            "from the live catalogs",
            result.stdout,
        )

    def test_destroy_without_state_and_record_has_nothing_to_destroy(self):
        objects = self.sandbox.platform.objects
        objects[f"{STATE_OBJECT}.tflock"] = b"stale"
        self.change_catalogs(self.offer_the_region_twice)
        for attempt in ("refund", "retry"):
            with self.subTest(attempt=attempt):
                result = self.sandbox.run("destroy-incus")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout.splitlines()[-1]),
                    {"destroyed": [], "state": "deleted"},
                )
                self.assertNotIn("live catalogs", result.stdout)
                self.assertEqual(self.sandbox.commands(), [])
                self.assertNotIn(f"{STATE_OBJECT}.tflock", objects)

    def test_a_malformed_record_refuses_before_tofu(self):
        catalog = json.loads(self.provision_record())["catalog"]
        cases = {
            b"{": "is no JSON document",
            b"[]": "names no provider",
            json.dumps({"provider": "aws", "catalog": catalog}).encode(): (
                "names no provider"
            ),
            json.dumps({"provider": "incus", "catalog": []}).encode(): "record",
            json.dumps({"provider": "incus", "catalog": {}}).encode(): (
                "offers no region 'default'"
            ),
        }
        for document, words in cases.items():
            with self.subTest(document=document):
                self.sandbox.platform.objects[RECORD_OBJECT] = document
                self.assert_refused(self.sandbox.run("destroy-incus"), words)

    def test_destroy_ends_with_the_addresses_it_destroyed(self):
        addresses = ["module.dns.dns_a_record_set.record[0]", "incus_instance.server"]
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.set_plan({"state": addresses, "outputs": {}})
        result = self.sandbox.run("destroy-incus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1]),
            {"destroyed": addresses, "state": "deleted"},
        )
        self.assertEqual(self.sandbox.commands(), ["init", "state", "destroy", "state"])

    def test_negative_control_resources_left_after_destroy_keep_the_state(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.set_plan(
            {"state": ["incus_instance.server"], "outputs": {}, "survivors": True}
        )
        result = self.sandbox.run("destroy-incus")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("still holds resources after tofu destroy", result.stderr)
        self.assertIn(STATE_OBJECT, self.sandbox.platform.objects)
        self.assertNotIn('"destroyed"', result.stdout)
        self.assertNotIn(
            "DELETE", [method for method, _ in self.sandbox.platform.s3_requests]
        )


if __name__ == "__main__":
    unittest.main()
