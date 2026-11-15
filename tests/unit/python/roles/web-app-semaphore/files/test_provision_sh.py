from __future__ import annotations

import fcntl
import json
import socket
import unittest
from pathlib import Path

from utils.cache.files import read_text

from .provision._fake_provision import (
    CUSTOMER_TOKEN,
    FILES,
    LOCK_ID,
    OUTPUTS,
    ROUTE53_KEYS,
    SNAPSHOT_RECORD,
    STATE_KEYS,
    TOKEN,
    WORKSPACE,
    ZONE,
    Sandbox,
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
KEPT_OBJECTS = (
    f"{WORKSPACE}-state/SO-2026/2.tfstate",
    f"{WORKSPACE}-state/SO-2026/1.dns.tfstate",
)


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


class TestCheckout(ProvisionCase):
    def test_provision_refuses_infrastructure_code_in_the_checkout(self):
        for relative in REFUSED:
            with self.subTest(file=relative):
                path = self.sandbox.checkout / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("planted", encoding="utf-8")
                self.assert_refused(self.sandbox.run("provision"), relative)
                path.unlink()
        clean = self.sandbox.run("provision")
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(self.sandbox.commands(), ["init", "apply", "output"])

    def test_destroy_refuses_infrastructure_code_in_the_checkout(self):
        (self.sandbox.checkout / "main.tf").write_text("planted", encoding="utf-8")
        self.assert_refused(self.sandbox.run("destroy"), "main.tf")

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
                self.assert_refused(self.sandbox.run("provision"))
        self.sandbox.tfvars().write_text('name = "SO-2026-1"\n', encoding="utf-8")
        self.assert_refused(self.sandbox.run("provision"), "is no JSON document")

    def test_a_tfvars_file_of_another_line_is_refused(self):
        self.sandbox.tfvars().unlink()
        self.assert_refused(
            self.sandbox.run("provision"), "provision/SO-2026-1.tfvars.json"
        )
        self.sandbox.tfvars({"name": "SO-2026-2"})
        self.assert_refused(self.sandbox.run("provision"), "not 'SO-2026-1'")

    def test_provision_reads_the_mounted_catalog_only(self):
        planted = {"cloud": {"sizes": {"huge": {}}, "regions": {"mars": {}}}}
        image_root = self.sandbox.core / "opentofu" / "roots" / "incus"
        for directory in (self.sandbox.checkout, image_root):
            (directory / "catalog.json").write_text(json.dumps(planted))
        result = self.sandbox.run("provision")
        self.assertEqual(result.returncode, 0, result.stderr)
        mounted = self.sandbox.catalogs / "incus.json"
        text = mounted.read_text()  # nocheck: cache-read tempdir
        self.assertEqual(self.call("apply")["texts"]["catalog.json"], text)
        self.sandbox.tfvars({"size": "huge", "region": "mars"})
        self.assert_refused(self.sandbox.run("provision"), "region 'mars'")
        self.sandbox.tfvars()
        (self.sandbox.catalogs / "incus.json").write_text("{}")
        self.assert_refused(
            self.sandbox.run("provision"),
            "no catalog offers region 'default'",
            "incus",
        )

    def test_provision_runs_the_image_module_with_a_clean_tf_env(self):
        result = self.sandbox.run(
            "provision",
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
            self.assertTrue(cwd.is_relative_to(self.sandbox.tmp))
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
        result = self.sandbox.run("provision")
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
        self.assertEqual(env["BAO_TOKEN"], TOKEN)
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
        result = self.sandbox.run("provision")
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
        for script in ("provision", "destroy", "unlock"):
            for name, values in cases.items():
                for value in values:
                    with self.subTest(script=script, name=name, value=value):
                        result = self.sandbox.run(script, **{name: value})
                        self.assert_refused(result, name)

    def test_provision_writes_workspace_json_from_the_environment(self):
        result = self.sandbox.run("provision")
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
                        self.sandbox.run("provision", **{name: value}), name
                    )
        for key in ("zone", "workspace"):
            with self.subTest(key=key):
                self.sandbox.tfvars({key: "chosen-by-the-checkout"})
                self.assert_refused(
                    self.sandbox.run("provision"), key, "is not a known key"
                )

    def test_the_task_directory_is_removed_on_every_exit(self):
        for fail, code in ((None, 0), ("apply", 1), ("init", 1)):
            with self.subTest(fail=fail):
                self.sandbox.log.unlink(missing_ok=True)
                self.sandbox.set_plan({"state": [], "outputs": {}, "fail": fail})
                result = self.sandbox.run("provision")
                self.assertEqual(result.returncode, code, result.stderr)
                for call in self.sandbox.calls():
                    task = Path(call["cwd"])
                    self.assertFalse(task.exists())
                    self.assertFalse((task / "backend.tfbackend").exists())
                    self.assertFalse((task / ".terraform").exists())
                self.assertEqual(list(self.sandbox.tmp.glob("provision-task-*")), [])


class TestBackendKeys(ProvisionCase):
    def test_backend_keys_come_from_a_private_file(self):
        result = self.sandbox.run(
            "provision", AWS_ACCESS_KEY_ID="planted", AWS_PROFILE="planted"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in self.sandbox.calls():
            self.assertEqual(key_findings(call, STATE_KEYS, {}), [])
        init = self.call("init")
        configs = [a for a in init["argv"] if a.startswith("-backend-config")]
        self.assertEqual(len(configs), 1)
        path = Path(configs[0].split("=", 1)[1])
        self.assertTrue(path.is_relative_to(Path(init["cwd"])))
        self.assertEqual(init["backend"]["mode"], 0o600)
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
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.set_plan({"state": ["hcloud_server.server"], "outputs": {}})
        result = self.sandbox.run("provision")
        self.assertEqual(result.returncode, 0, result.stderr)
        allowed = {
            "AWS_ACCESS_KEY_ID": ROUTE53_KEYS["access_key"],
            "AWS_SECRET_ACCESS_KEY": ROUTE53_KEYS["secret_key"],
        }
        for call in self.sandbox.calls():
            self.assertEqual(key_findings(call, STATE_KEYS, allowed), [])


class TestTakenName(ProvisionCase):
    def test_provision_refuses_a_name_that_holds_an_address(self):
        self.sandbox.dns.records[(f"app.{WORKSPACE}.{ZONE}", 1)] = [
            socket.inet_aton("198.51.100.7")
        ]
        result = self.sandbox.run("provision")
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
        result = self.sandbox.run("provision")
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
        for script in ("provision", "destroy"):
            with self.subTest(script=script):
                self.assert_no_state_write(script, "has no backup")

    def test_a_snapshot_older_than_the_key_refuses_before_any_state_write(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.platform.secrets[SNAPSHOT_RECORD] = {
            "key_created_at": "1763000005",
            "snapshot_at": "1763000000",
        }
        for script in ("provision", "destroy"):
            with self.subTest(script=script):
                self.assert_no_state_write(script, "predates the transit key")

    def test_negative_control_without_the_snapshot_check_a_younger_key_writes(self):
        self.sandbox.platform.secrets[SNAPSHOT_RECORD] = {
            "key_created_at": "1763000005",
            "snapshot_at": "1763000000",
        }
        text = read_text(str(FILES / "python" / "provision.py"))
        planted = text.replace(
            "        require_snapshot(self.bao, self.workspace)\n        if self.empty():",
            "        if self.empty():",
        )
        self.assertNotEqual(planted, text)
        (self.sandbox.core / "python" / "provision.py").write_text(planted)
        result = self.sandbox.run("provision")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apply", self.sandbox.commands())

    def test_a_malformed_snapshot_record_refuses(self):
        self.sandbox.platform.secrets[SNAPSHOT_RECORD] = {
            "key_created_at": "yesterday",
            "snapshot_at": "1763000000",
        }
        self.assert_no_state_write("provision", "has no backup")

    def test_a_snapshot_after_the_key_admits_the_write(self):
        result = self.sandbox.run("provision")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(SNAPSHOT_RECORD, self.sandbox.platform.reads)
        self.assertIn("apply", self.sandbox.commands())

    def test_unlock_writes_no_state_and_needs_no_snapshot(self):
        del self.sandbox.platform.secrets[SNAPSHOT_RECORD]
        result = self.sandbox.run("unlock")
        self.assertEqual(result.returncode, 0, result.stderr)


class TestArguments(ProvisionCase):
    def test_each_script_refuses_an_extra_argument(self):
        for script in ("provision", "destroy", "unlock", "dns"):
            with self.subTest(script=script):
                self.assert_refused(
                    self.sandbox.run(script, "-destroy"), "takes no argument"
                )

    def test_destroy_destroys_with_the_checkout_values(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        result = self.sandbox.run("destroy")
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
        result = self.sandbox.run("provision", PROVIDER_TOKEN=token)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(CUSTOMER_TOKEN, result.stdout + result.stderr)
        for call in self.sandbox.calls():
            self.assertFalse(any(CUSTOMER_TOKEN in arg for arg in call["argv"]))
        return self.call("apply")["env"]

    def test_platform_takes_the_platform_token_only(self):
        env = self.apply_env("platform")
        self.assertEqual(env["HCLOUD_TOKEN"], "hcloud-platform-token")
        self.assertNotIn(CUSTOMER_PATH, self.sandbox.platform.reads)

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
                    self.sandbox.run("provision", PROVIDER_TOKEN="workspace"),
                    CUSTOMER_PATH,
                    "holds no token",
                )

    def test_destroy_takes_the_same_token_as_provision(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        result = self.sandbox.run("destroy", PROVIDER_TOKEN="workspace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call("destroy")["env"]["HCLOUD_TOKEN"], CUSTOMER_TOKEN)

    def test_a_missing_or_unknown_provider_token_is_refused(self):
        for value in (None, "", "customer", "Platform"):
            with self.subTest(value=value):
                self.assert_refused(
                    self.sandbox.run("provision", PROVIDER_TOKEN=value),
                    "PROVIDER_TOKEN",
                )

    def test_a_provider_without_customer_tokens_refuses_workspace(self):
        self.sandbox.tfvars({"size": "cx22", "region": "scs1"})
        self.assert_refused(
            self.sandbox.run("provision", PROVIDER_TOKEN="workspace"),
            "PROVIDER_TOKEN",
            "scs takes no customer token",
        )


class TestStateCleanup(ProvisionCase):
    def plant(self):
        objects = self.sandbox.platform.objects
        for key in (STATE_OBJECT, f"{STATE_OBJECT}.tflock", *KEPT_OBJECTS):
            objects[key] = b"encrypted"
        objects[RECORD_OBJECT] = self.provision_record()
        return objects

    def test_destroy_deletes_the_state_and_its_lock_after_tofu_destroy(self):
        objects = self.plant()
        result = self.sandbox.run("destroy")
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
        result = self.sandbox.run("destroy")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(STATE_OBJECT, objects)
        self.assertIn(RECORD_OBJECT, objects)
        self.assertNotIn(
            "DELETE", [method for method, _ in self.sandbox.platform.s3_requests]
        )


class TestProvisionRecord(ProvisionCase):
    def provision(self):
        result = self.sandbox.run("provision")
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
        result = self.sandbox.run("destroy")
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
        result = self.sandbox.run("provision")
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
            self.sandbox.run("provision"),
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
        result = self.sandbox.run("provision")
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
                self.assert_refused(self.sandbox.run("destroy"), words)

    def test_destroy_without_a_record_falls_back_to_the_live_catalogs(self):
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        result = self.sandbox.run("destroy")
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
                result = self.sandbox.run("destroy")
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
                self.assert_refused(self.sandbox.run("destroy"), words)

    def test_destroy_ends_with_the_addresses_it_destroyed(self):
        addresses = ["module.dns.dns_a_record_set.record[0]", "incus_instance.server"]
        self.sandbox.platform.objects[STATE_OBJECT] = b"encrypted"
        self.sandbox.set_plan({"state": addresses, "outputs": {}})
        result = self.sandbox.run("destroy")
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
        result = self.sandbox.run("destroy")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("still holds resources after tofu destroy", result.stderr)
        self.assertIn(STATE_OBJECT, self.sandbox.platform.objects)
        self.assertNotIn('"destroyed"', result.stdout)
        self.assertNotIn(
            "DELETE", [method for method, _ in self.sandbox.platform.s3_requests]
        )


if __name__ == "__main__":
    unittest.main()
