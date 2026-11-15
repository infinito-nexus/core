from __future__ import annotations

import json
import re
import unittest

import jinja2

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles" / "svc-dns-knot"
TEMPLATE = read_text(str(ROLE_DIR / "templates" / "knot.conf.j2"))
VARS = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)))
VOLUMES = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_VOLUMES)))
WORKSPACE_TASKS = load_yaml_str(read_text(str(ROLE_DIR / "tasks" / "workspace.yml")))
CREDENTIALS = json.loads(
    read_text(
        str(
            PROJECT_ROOT
            / "roles"
            / "web-app-semaphore"
            / "files"
            / "opentofu"
            / "credentials.json"
        )
    )
)
ZONE = "ws.example.org"
FIRST = "ws-4f1c2a3e-1b2c-4d5e-8f90-0123456789ab"
SECOND = "ws-00000000-0000-4000-8000-000000000000"
KEYS = {FIRST: "Zmlyc3Qtd29ya3NwYWNlLWtleQ==", SECOND: "c2Vjb25kLXdvcmtzcGFjZS1rZXk="}
ADDRESSES = ("192.0.2.1", "192.0.2.2", "192.0.2.3")
UPDATE_FIELDS = {
    "id",
    "key",
    "action",
    "update-owner",
    "update-owner-match",
    "update-type",
}


def render(template=TEMPLATE, primary=True, keys=None, addresses=ADDRESSES, types=None):
    """Args:
        template: the text of ``knot.conf.j2``.
        primary: whether the host is the primary of its group.
        keys: ``{ws-<id>: secret}`` the primary grants updates to.
        addresses: the addresses of the group, the primary first.
        types: the record types a workspace key may change.

    Returns:
        The rendered configuration, parsed.
    """
    environment = jinja2.Environment(
        trim_blocks=True,
        undefined=jinja2.StrictUndefined,
        autoescape=jinja2.select_autoescape(default_for_string=False),
    )
    text = environment.from_string(template).render(
        knot_primary=primary,
        knot_workspace_keys=KEYS if keys is None else keys,
        KNOT_ZONE=ZONE,
        KNOT_ADDRESSES=list(addresses),
        KNOT_PORT=53,
        KNOT_TRANSFER_SECRET="dHJhbnNmZXItc2VjcmV0",
        KNOT_UPDATE_TYPES=VARS["KNOT_UPDATE_TYPES"] if types is None else types,
        KNOT_WORKSPACE_ALGORITHM=VARS["KNOT_WORKSPACE_ALGORITHM"],
        KNOT_STORAGE_TARGET=VOLUMES["data"]["mounts"][0]["target"],
        KNOT_ZONE_TARGET=VOLUMES["zone"]["mounts"][0]["target"],
    )
    return load_yaml_str(text)


def acl_findings(config, workspaces):
    """Args:
        config: a parsed primary configuration.
        workspaces: the ``ws-<id>`` the primary grants updates to.

    Returns:
        One message per update grant beyond 104 decision 9: a grant without
        its own key, a key shared by two grants, an owner rule other than
        ``key`` with ``sub-or-equal``, a type beyond A, AAAA, CNAME and TXT, an
        extra condition, a grant missing from the zone, and a workspace key
        bound to no grant.
    """
    findings = []
    keys = {key["id"] for key in config.get("key", [])}
    acls = config.get("acl", [])
    granted = set(config["zone"][0].get("acl", []))
    bound = {}
    for acl in acls:
        action = acl.get("action")
        if isinstance(action, list) and "update" in action:
            findings.append(f"{acl.get('id')}: update shares a grant with {action}")
        if action != "update":
            continue
        name, key = acl.get("id"), acl.get("key")
        if key not in keys:
            findings.append(f"{name}: no key of its own")
        elif key in bound:
            findings.append(f"{name}: shares the key {key} with {bound[key]}")
        bound[key] = name
        if acl.get("update-owner") != "key":
            findings.append(f"{name}: update-owner is {acl.get('update-owner')}")
        if acl.get("update-owner-match") != "sub-or-equal":
            findings.append(
                f"{name}: update-owner-match is {acl.get('update-owner-match')}"
            )
        if sorted(acl.get("update-type") or []) != ["A", "AAAA", "CNAME", "TXT"]:
            findings.append(f"{name}: update-type is {acl.get('update-type')}")
        if set(acl) != UPDATE_FIELDS:
            findings.append(f"{name}: carries {sorted(set(acl) ^ UPDATE_FIELDS)}")
        if name not in granted:
            findings.append(f"{name}: is not on the zone")
    expected = {f"{workspace}.{ZONE}." for workspace in workspaces}
    if set(bound) != expected:
        findings.append(f"bound keys {sorted(bound)} differ from {sorted(expected)}")
    return findings


class TestAcl(unittest.TestCase):
    def test_the_knot_acl_binds_each_key_to_its_names(self):
        config = render()
        self.assertEqual(acl_findings(config, KEYS), [])
        workspace_keys = {key["id"]: key for key in config["key"]}
        for workspace, secret in KEYS.items():
            key = workspace_keys[f"{workspace}.{ZONE}."]
            self.assertEqual(key["algorithm"], "hmac-sha512")
            self.assertEqual(key["secret"], secret)

    def test_negative_control_a_dropped_owner_rule_fails(self):
        planted = TEMPLATE.replace("    update-owner: key\n", "")
        self.assertNotEqual(planted, TEMPLATE)
        self.assertNotEqual(acl_findings(render(planted), KEYS), [])

    def test_negative_control_an_added_type_fails(self):
        types = [*VARS["KNOT_UPDATE_TYPES"], "NS"]
        self.assertNotEqual(acl_findings(render(types=types), KEYS), [])

    def test_negative_control_a_widened_owner_match_fails(self):
        planted = TEMPLATE.replace("sub-or-equal", "pattern")
        self.assertNotEqual(acl_findings(render(planted), KEYS), [])

    def test_negative_control_a_shared_key_fails(self):
        planted = TEMPLATE.replace(
            "    key: {{ workspace }}.{{ KNOT_ZONE }}.\n    action: update",
            "    key: transfer\n    action: update",
        )
        self.assertNotEqual(planted, TEMPLATE)
        self.assertNotEqual(acl_findings(render(planted), KEYS), [])

    def test_without_workspaces_only_the_transfer_grant_remains(self):
        config = render(keys={})
        self.assertEqual(acl_findings(config, {}), [])
        self.assertEqual(
            config["acl"], [{"id": "transfer", "key": "transfer", "action": "transfer"}]
        )
        self.assertEqual(config["zone"][0]["acl"], ["transfer"])
        self.assertEqual([key["id"] for key in config["key"]], ["transfer"])


class TestTransfer(unittest.TestCase):
    def test_the_primary_signs_and_notifies_every_secondary(self):
        config = render()
        (zone,) = config["zone"]
        self.assertEqual(zone["domain"], ZONE)
        self.assertIs(zone["dnssec-signing"], True)
        self.assertEqual(zone["dnssec-policy"], "subzone")
        self.assertEqual(zone["notify"], ["secondary-1", "secondary-2"])
        self.assertEqual(
            {(r["id"], r["address"], r["key"]) for r in config["remote"]},
            {
                ("secondary-1", "192.0.2.2@53", "transfer"),
                ("secondary-2", "192.0.2.3@53", "transfer"),
            },
        )
        self.assertNotIn("master", zone)

    def test_a_secondary_takes_the_signed_zone_by_transfer_only(self):
        config = render(primary=False)
        (zone,) = config["zone"]
        self.assertEqual(zone["master"], "primary")
        self.assertEqual(zone["acl"], ["notify"])
        self.assertNotIn("dnssec-signing", zone)
        self.assertNotIn("file", zone)
        self.assertNotIn("policy", config)
        self.assertEqual(
            config["remote"],
            [{"id": "primary", "address": "192.0.2.1@53", "key": "transfer"}],
        )
        self.assertEqual([key["id"] for key in config["key"]], ["transfer"])
        self.assertEqual(
            config["acl"], [{"id": "notify", "key": "transfer", "action": "notify"}]
        )

    def test_a_single_host_renders_no_remote_and_no_notify(self):
        config = render(addresses=ADDRESSES[:1])
        self.assertNotIn("remote", config)
        self.assertNotIn("notify", config["zone"][0])

    def test_the_server_reads_the_paths_its_volumes_mount(self):
        config = render()
        self.assertEqual(
            config["database"]["storage"], VOLUMES["data"]["mounts"][0]["target"]
        )
        self.assertEqual(
            config["zone"][0]["file"], VOLUMES["zone"]["mounts"][0]["target"]
        )

    def test_the_configuration_holding_the_tsig_keys_mounts_as_a_secret(self):
        self.assertTrue(all(key["secret"] for key in render()["key"]))
        self.assertEqual(VOLUMES["conf"]["type"], "secret")


class TestWorkspaceSecret(unittest.TestCase):
    def setUp(self):
        self.write = next(
            task
            for task in WORKSPACE_TASKS
            if task.get("ansible.builtin.include_role", {}).get("tasks_from")
            == "utils/kv.yml"
        )
        self.secret = next(
            task["ansible.builtin.set_fact"]["knot_workspace_secret"]
            for task in WORKSPACE_TASKS
            if "knot_workspace_secret" in task.get("ansible.builtin.set_fact", {})
        )

    def test_the_key_lands_where_the_provision_runner_reads_it(self):
        knot = CREDENTIALS["dns"]["knot"]
        mount, _, path = knot["path"].partition("/data/")
        variables = self.write["vars"]
        self.assertEqual(variables["openbao_kv_mount"], mount)
        self.assertEqual(
            variables["openbao_kv_path"].replace("{{ knot_workspace }}", "{workspace}"),
            path,
        )
        self.assertEqual(variables["openbao_kv_data"], "{{ knot_workspace_secret }}")
        fields = set(re.findall(r"'(\w+)':", self.secret))
        self.assertEqual(fields, set(knot["env"].values()))

    def test_destroy_deletes_the_secret_and_apply_writes_it(self):
        state = self.write["vars"]["openbao_kv_state"]
        self.assertIn("'present' if WORKSPACE_ACTION == 'apply' else 'absent'", state)

    def test_a_malformed_workspace_is_refused(self):
        (pattern,) = re.findall(
            r"match\('(.+)'\)", WORKSPACE_TASKS[0]["ansible.builtin.assert"]["that"][0]
        )
        uuid = FIRST.removeprefix("ws-")
        self.assertRegex(uuid, pattern)
        for value in ("ws-1", "ws-../x", FIRST, f"{uuid}.evil", uuid.upper()):
            with self.subTest(value=value):
                self.assertNotRegex(value, pattern)

    def test_the_key_name_is_the_ws_name_the_playbook_and_provision_use(self):
        (name,) = (
            task["ansible.builtin.set_fact"]["knot_workspace"]
            for task in WORKSPACE_TASKS
            if "knot_workspace" in task.get("ansible.builtin.set_fact", {})
        )
        self.assertEqual(name, "ws-{{ WORKSPACE }}")

    def test_apply_hands_the_subzone_to_semaphore_with_an_empty_zone_id(self):
        (task,) = (
            task
            for task in WORKSPACE_TASKS
            if "workspace_dns" in task.get("ansible.builtin.set_fact", {})
        )
        self.assertEqual(
            task["ansible.builtin.set_fact"]["workspace_dns"],
            {"zone": "{{ KNOT_ZONE }}", "zone_id": ""},
        )
        self.assertEqual(task["when"], "WORKSPACE_ACTION == 'apply'")
        order = load_yaml_str(read_text(str(PROJECT_ROOT / "playbook-workspace.yml")))
        roles = order[0]["vars"]["workspace_roles"]
        self.assertLess(roles.index("svc-dns-knot"), roles.index("web-app-semaphore"))


if __name__ == "__main__":
    unittest.main()
