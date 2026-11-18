from __future__ import annotations

import copy
import importlib.util
import json
import re
import unittest

import jinja2
from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from ansible.plugins.test.core import TestModule as CoreTests
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)

from .files._semaphore_fake import (
    ALIAS,
    FakeSemaphore,
    decoded,
    load_project,
    platform_spec,
    workspace_spec,
)

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-semaphore"
WORKSPACE_TASKS = ROLE_DIR / "tasks" / "workspace.yml"
ADMIN_TASKS = ROLE_DIR / "tasks" / "utils" / "admin.yml"
APPLY_DIR = ROLE_DIR / "tasks" / "flavors" / "dns" / "workspace"
DNS_STEPS = ROLE_DIR / "tasks" / "utils" / "workspace" / "dns.yml"
RUNNER_SQL = ROLE_DIR / "templates" / "sql" / "workspace" / "runner.sql.j2"
PROVISION = "Infinito.Nexus Provision"
TEMPLATES = ("provision", "destroy", "dns")
FLAVOR_VALUES = {
    "knot": {"zone": "ws.example.org", "zone_id": ""},
    "route53": {"zone": "ws.example.org", "zone_id": "Z0123456789ABCDEFGHIJ"},
    "cloudflare": {
        "zone": "example.com",
        "zone_id": "023e105f4ecef8ad9ca31a8372d0c353",
    },
}
SERVICES = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_SERVICES)))
VARIANTS = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_VARIANTS)))
SECRETS = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_SECRETS)))
VARS_TEXT = read_text(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
CREDENTIALS = json.loads(
    read_text(str(ROLE_DIR / "files" / "opentofu" / "credentials.json"))
)
KV_UTIL = load_yaml_str(
    read_text(
        str(PROJECT_ROOT / "roles" / "web-app-openbao" / "tasks" / "utils" / "kv.yml")
    )
)
DNS_WRITES = load_yaml_str(
    read_text(str(ROLE_DIR / "tasks" / "utils" / "dns_credentials.yml"))
)
MASKED = "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"
SECRET_REFERENCES = re.compile(r"openbao_kv_data|openbao_kv_login|secret_id")
ROUTE53 = {
    "route53_access_key_id": "AKIAEXAMPLE",
    "route53_secret_access_key": "route53-admin-secret",
}
WORKSPACE = "ws-4f1c2a3e-1b2c-4d5e-8f90-0123456789ab"
OTHER = "ws-00000000-0000-4000-8000-000000000000"
ZONE_ID = "Z0123456789ABC"
SUBZONE = "ws.example.org"
NAMES_KEY = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
TYPES_KEY = "route53:ChangeResourceRecordSetsRecordTypes"
KEY_FIELD = CREDENTIALS["dns"]["route53"]["env"]["AWS_ACCESS_KEY_ID"]
SECRET_FIELD = CREDENTIALS["dns"]["route53"]["env"]["AWS_SECRET_ACCESS_KEY"]
KEPT = {"minted": False, "access_key_id": "AKIAWORKSPACE", "secret_access_key": None}
MINTED = {"minted": True, "access_key_id": "AKIANEW", "secret_access_key": "new-secret"}
ROUTE53_STEPS = ("admin", "zone", "place", "policy", "read", "user", "write")
ADMIN_PATH = "platform/data/workspaces/route53"
ADMIN_ARGS = {
    "admin_access_key_id": "{{ semaphore_route53_admin.access_key_id }}",
    "admin_secret_access_key": "{{ semaphore_route53_admin.secret_access_key }}",
}
COMMANDS = frozenset(
    {
        "ansible.builtin.command",
        "ansible.builtin.shell",
        "ansible.builtin.raw",
        "ansible.builtin.script",
        "command",
        "shell",
        "raw",
        "script",
    }
)
INCLUDES = frozenset(
    {
        "ansible.builtin.include_role",
        "ansible.builtin.include_tasks",
        "include_role",
        "include_tasks",
    }
)
CREDENTIAL = re.compile(
    r"\b(?:semaphore_route53_admin|semaphore_route53_user|openbao_kv_current"
    r"|held_access_key_id|admin_access_key_id|admin_secret_access_key)\b"
)


def _load():
    path = ROLE_DIR / "filter_plugins" / "semaphore_dns.py"
    spec = importlib.util.spec_from_file_location("semaphore_dns", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dns = _load()


def _actions(statement):
    action = statement["Action"]
    return [action] if isinstance(action, str) else list(action)


def policy_findings(policy, workspace, zone_id, subzone):
    """Args:
        policy: a rendered IAM policy document.
        workspace: the workspace it was rendered for.
        zone_id: the subzone's hosted zone.
        subzone: the subzone.

    Returns:
        One message per grant beyond 104 decision 9 and 120 decision 1.
    """
    zone = f"arn:aws:route53:::hostedzone/{zone_id}"
    expected = {
        ("route53:ChangeResourceRecordSets", zone),
        ("route53:GetHostedZone", zone),
        ("route53:ListResourceRecordSets", zone),
        ("route53:GetChange", "arn:aws:route53:::change/*"),
    }
    findings = []
    granted = set()
    for statement in policy["Statement"]:
        if statement.get("Effect") != "Allow":
            findings.append(f"{statement.get('Sid')} is no Allow")
        for action in _actions(statement):
            granted.add((action, statement["Resource"]))
            if action != "route53:ChangeResourceRecordSets":
                if statement.get("Condition"):
                    findings.append(f"{action} carries a condition")
                continue
            condition = statement.get("Condition", {})
            like = condition.get("ForAllValues:StringLike", {}).get(NAMES_KEY)
            if like != [f"*.{workspace}.{subzone}"]:
                findings.append(f"{action} names {like}")
            types = condition.get("ForAllValues:StringEquals", {}).get(TYPES_KEY)
            if sorted(types or []) != ["A", "AAAA", "CNAME", "TXT"]:
                findings.append(f"{action} allows the types {types}")
            if set(condition) != {
                "ForAllValues:StringLike",
                "ForAllValues:StringEquals",
            }:
                findings.append(f"{action} has the conditions {sorted(condition)}")
    for action, resource in sorted(granted ^ expected):
        findings.append(f"{action} on {resource} differs from the four grants")
    return findings


def statement(policy, sid):
    return next(s for s in policy["Statement"] if s["Sid"] == sid)


def credential_write_findings(writes, util):
    """Args:
        writes: the parsed ``web-app-semaphore/tasks/utils/dns_credentials.yml``.
        util: the parsed ``web-app-openbao/tasks/utils/kv.yml``.

    Returns:
        One message per write that bypasses the shared KV util or shows its
        data in a loop label, per secret on a command line, and per task that
        hands a value on stdin without the masking idiom.
    """
    findings = []
    for task in writes:
        name = task.get("name", "")
        include = task.get("ansible.builtin.include_role", {})
        if include != {"name": "web-app-openbao", "tasks_from": "utils/kv.yml"}:
            findings.append(f"{name}: writes past web-app-openbao utils/kv.yml")
        if task.get("vars", {}).get("openbao_kv_state") != "present":
            findings.append(f"{name}: no state present")
        label = str(task.get("loop_control", {}).get("label", ""))
        if not label or "data" in label or label.strip("{} ") == "semaphore_dns_write":
            findings.append(f"{name}: the loop label shows the data")
    stdin_data = False
    for task in util:
        shell = task.get("ansible.builtin.shell")
        if not isinstance(shell, dict):
            continue
        name = task.get("name", "")
        if SECRET_REFERENCES.search(str(shell.get("cmd", ""))):
            findings.append(f"{name}: a secret on the command line")
        stdin = str(shell.get("stdin", ""))
        stdin_data |= "openbao_kv_data" in stdin
        if stdin and task.get("no_log") != MASKED:
            findings.append(f"{name}: stdin without no_log {MASKED}")
    if not stdin_data:
        findings.append("no task hands openbao_kv_data on stdin")
    return findings


class TestFlavors(unittest.TestCase):
    def test_every_dns_flavor_has_its_variant(self):
        workspaces = SERVICES["semaphore"]["workspaces"]
        self.assertEqual(workspaces["dns"]["flavor"], "knot")
        self.assertEqual(set(dns.FLAVORS), {"knot", "route53", "cloudflare"})
        for flavor in dns.FLAVORS:
            with self.subTest(flavor=flavor):
                self.assertEqual(dns.semaphore_dns_flavor(flavor), flavor)
                self.assertTrue(
                    (ROLE_DIR / "tasks" / "flavors" / "dns" / f"{flavor}.yml").is_file()
                )
        with self.assertRaisesRegex(AnsibleFilterError, "expected one of"):
            dns.semaphore_dns_flavor("bind")
        rows = [
            ((v.get("services", {}).get("semaphore") or {}).get("workspaces") or {})
            .get("dns", {})
            .get("flavor")
            for v in VARIANTS
        ]
        self.assertEqual(rows.count("route53"), 1)
        self.assertEqual(rows.count("cloudflare"), 1)

    def test_a_flavor_without_credentials_reports_not_run(self):
        base = SERVICES["semaphore"]["workspaces"]["dns"]
        cases = {
            "knot": ({}, []),
            "route53": (
                {"route53_access_key_id": "AKIA", "route53_secret_access_key": ""},
                ["secrets.credentials.route53_secret_access_key"],
            ),
            "cloudflare": (
                {"cloudflare_zone_tokens": ""},
                ["secrets.credentials.cloudflare_zone_tokens"],
            ),
        }
        for flavor, (credentials, missing) in cases.items():
            with self.subTest(flavor=flavor):
                live = dns.semaphore_dns_live({**base, "flavor": flavor}, credentials)
                self.assertEqual(live["missing"], missing)
                self.assertIs(live["run"], not missing)
                if missing:
                    self.assertIn("live checks not run, missing", live["message"])
                    self.assertIn(missing[0], live["message"])
        live = dns.semaphore_dns_live({"flavor": "route53"}, ROUTE53)
        self.assertEqual(live["message"], "dns flavor route53: live checks run")
        self.assertNotIn(ROUTE53["route53_secret_access_key"], str(live))

    def test_negative_control_a_credential_under_services_is_ignored(self):
        placed = {
            "flavor": "cloudflare",
            "cloudflare": {"zones": {"a.example": "token-under-services"}},
            "cloudflare_zone_tokens": json.dumps({"a.example": "token-under-services"}),
            "route53": {"access_key": "AKIA", "secret_key": "under-services"},
        }
        self.assertFalse(dns.semaphore_dns_live(placed, {})["run"])
        self.assertEqual(dns.semaphore_dns_writes({}, placed), [])
        self.assertFalse(
            dns.semaphore_dns_live({**placed, "flavor": "route53"}, {})["run"]
        )

    def test_the_dns_credentials_are_plain_secrets_not_services(self):
        declared = SECRETS["credentials"]
        for key in (
            "route53_access_key_id",
            "route53_secret_access_key",
            "cloudflare_zone_tokens",
        ):
            with self.subTest(key=key):
                self.assertEqual(declared[key]["algorithm"], "plain")
                self.assertIn(
                    f"lookup('config', application_id, 'secrets.credentials.{key}')",
                    VARS_TEXT,
                )
        dns_config = SERVICES["semaphore"]["workspaces"]["dns"]
        self.assertEqual(
            set(dns_config), {"flavor", "zone", "record_limit", "zone_probe"}
        )
        self.assertEqual(dns_config["record_limit"], 0)
        self.assertEqual(dns_config["zone_probe"], "")
        self.assertIn("semaphore_dns_live(SEMAPHORE_DNS_CREDENTIALS)", VARS_TEXT)


ZONES_SECRETS = {
    "cloudflare_zones_token": "zones-token",
    "cloudflare_zones_account_id": "0123456789abcdef0123456789abcdef",
}


class TestCredentialWrites(unittest.TestCase):
    def test_the_zone_token_lands_where_the_zone_template_reads_it(self):
        write = dns.semaphore_cloudflare_zones_write(ZONES_SECRETS)
        read = CREDENTIALS["zone"]
        self.assertEqual(f"{write['mount']}/data/{write['path']}", read["path"])
        self.assertEqual(set(write["data"]), set(read["env"].values()))
        self.assertEqual(write["data"]["token"], "zones-token")
        self.assertEqual(write["state"], "present")

    def test_a_missing_zone_secret_deletes_the_record(self):
        for name in ZONES_SECRETS:
            with self.subTest(missing=name):
                write = dns.semaphore_cloudflare_zones_write(
                    {**ZONES_SECRETS, name: ""}
                )
                self.assertEqual((write["state"], write["data"]), ("absent", {}))

    def test_the_zones_url_is_the_api_of_the_zone_entry(self):
        self.assertEqual(
            dns.semaphore_opentofu_credentials("zone")["api"],
            CREDENTIALS["zone"]["api"],
        )
        self.assertIn("('zone' | semaphore_opentofu_credentials).api", VARS_TEXT)

    def test_route53_writes_its_pair_to_the_workspace_operation_path(self):
        (write,) = dns.semaphore_dns_writes(ROUTE53, {"flavor": "route53"})
        self.assertEqual(
            (write["mount"], write["path"]), ("platform", "workspaces/route53")
        )
        self.assertEqual(
            write["data"],
            {
                "access_key_id": "AKIAEXAMPLE",
                "secret_access_key": "route53-admin-secret",
            },
        )
        self.assertEqual(set(write), {"mount", "path", "data"})

    def test_cloudflare_writes_each_zone_token_where_provision_reads_it(self):
        tokens = {"b.example": "token-b", "a.example": "token-a"}
        writes = dns.semaphore_dns_writes(
            {"cloudflare_zone_tokens": json.dumps(tokens)}, {"flavor": "cloudflare"}
        )
        self.assertEqual(
            [(w["mount"], w["path"], w["data"]) for w in writes],
            [
                ("platform", "provision/cloudflare/b.example", {"token": "token-b"}),
                ("platform", "provision/cloudflare/a.example", {"token": "token-a"}),
            ],
        )
        read = CREDENTIALS["dns"]["cloudflare"]
        self.assertEqual(read["path"], "platform/data/provision/cloudflare/{zone}")
        self.assertEqual(read["env"], {"CLOUDFLARE_API_TOKEN": "token"})

    def test_knot_and_missing_credentials_write_nothing(self):
        self.assertEqual(dns.semaphore_dns_writes(ROUTE53, {"flavor": "knot"}), [])
        self.assertEqual(
            dns.semaphore_dns_writes(
                {"route53_access_key_id": "AKIA"}, {"flavor": "route53"}
            ),
            [],
        )

    def test_malformed_zone_tokens_fail_without_their_value(self):
        for raw in (
            "{not json",
            json.dumps(["a.example"]),
            json.dumps({"../escape": "secret-value-1"}),
            json.dumps({"A.Example": "secret-value-1"}),
            json.dumps({"a.example": ""}),
            json.dumps({"a.example": "secret-value-1", "b.example": "secret-value-1"}),
        ):
            with (
                self.subTest(raw=raw),
                self.assertRaises(AnsibleFilterError) as caught,
            ):
                dns.semaphore_dns_live(
                    {"flavor": "cloudflare"}, {"cloudflare_zone_tokens": raw}
                )
            self.assertNotIn("secret-value-1", str(caught.exception))

    def test_the_writes_keep_values_off_argv_and_out_of_the_log(self):
        self.assertEqual(credential_write_findings(DNS_WRITES, KV_UTIL), [])

    def test_negative_control_a_value_on_argv_fails(self):
        util = copy.deepcopy(KV_UTIL)
        write = next(t for t in util if "openbao_kv_data" in str(t))
        write["ansible.builtin.shell"]["cmd"] += " {{ openbao_kv_data | to_json }}"
        self.assertNotEqual(credential_write_findings(DNS_WRITES, util), [])

    def test_negative_control_an_unmasked_stdin_task_fails(self):
        util = copy.deepcopy(KV_UTIL)
        next(t for t in util if "openbao_kv_data" in str(t)).pop("no_log")
        self.assertNotEqual(credential_write_findings(DNS_WRITES, util), [])

    def test_negative_control_a_label_with_the_data_fails(self):
        writes = copy.deepcopy(DNS_WRITES)
        writes[0]["loop_control"]["label"] = "{{ semaphore_dns_write }}"
        self.assertNotEqual(credential_write_findings(writes, KV_UTIL), [])

    def test_negative_control_a_write_past_the_shared_util_fails(self):
        writes = copy.deepcopy(DNS_WRITES)
        writes[0]["ansible.builtin.include_role"]["tasks_from"] = "utils/kv_put.yml"
        self.assertNotEqual(credential_write_findings(writes, KV_UTIL), [])


class TestRoute53Policy(unittest.TestCase):
    def setUp(self):
        self.policy = dns.semaphore_route53_policy(WORKSPACE, ZONE_ID, SUBZONE)

    def assert_breaks(self, policy):
        self.assertNotEqual(policy_findings(policy, WORKSPACE, ZONE_ID, SUBZONE), [])

    def test_the_route53_policy_is_scoped_to_its_names(self):
        self.assertEqual(policy_findings(self.policy, WORKSPACE, ZONE_ID, SUBZONE), [])
        self.assert_breaks(dns.semaphore_route53_policy(OTHER, ZONE_ID, SUBZONE))
        for value in ("", "*"):
            with self.subTest(value=value), self.assertRaises(AnsibleFilterError):
                dns.semaphore_route53_policy(value, ZONE_ID, SUBZONE)

    def test_negative_control_a_widened_name_fails(self):
        condition = statement(self.policy, "ChangeOwnNames")["Condition"]
        condition["ForAllValues:StringLike"][NAMES_KEY] = [f"*.{SUBZONE}"]
        self.assert_breaks(self.policy)

    def test_negative_control_a_dropped_for_all_values_fails(self):
        condition = statement(self.policy, "ChangeOwnNames")["Condition"]
        condition["StringLike"] = condition.pop("ForAllValues:StringLike")
        self.assert_breaks(self.policy)

    def test_negative_control_an_added_type_fails(self):
        condition = statement(self.policy, "ChangeOwnNames")["Condition"]
        condition["ForAllValues:StringEquals"][TYPES_KEY].append("NS")
        self.assert_breaks(self.policy)

    def test_the_route53_policy_holds_exactly_four_actions(self):
        actions = [a for s in self.policy["Statement"] for a in _actions(s)]
        self.assertEqual(
            sorted(actions),
            [
                "route53:ChangeResourceRecordSets",
                "route53:GetChange",
                "route53:GetHostedZone",
                "route53:ListResourceRecordSets",
            ],
        )

    def test_negative_control_a_dropped_get_change_fails(self):
        self.policy["Statement"].remove(statement(self.policy, "ReadChange"))
        self.assert_breaks(self.policy)

    def test_negative_control_a_list_on_every_zone_fails(self):
        read = statement(self.policy, "ReadZone")
        read["Action"] = ["route53:GetHostedZone"]
        self.policy["Statement"].append(
            {
                "Sid": "ListAll",
                "Effect": "Allow",
                "Action": "route53:ListResourceRecordSets",
                "Resource": "*",
            }
        )
        self.assert_breaks(self.policy)

    def test_negative_control_route53_star_fails(self):
        widened = copy.deepcopy(self.policy)
        statement(widened, "ReadZone")["Action"].append("route53:*")
        self.assert_breaks(widened)


class TestCloudflareZones(unittest.TestCase):
    def test_apply_places_a_workspace_in_a_zone_with_room(self):
        pool = {
            "cloudflare_zone_tokens": json.dumps(
                {"a.example": "token-a", "b.example": "token-b"}
            )
        }
        place = dns.semaphore_cloudflare_zone
        self.assertEqual(
            place(pool, {"a.example": 3, "b.example": 0}, 200), "a.example"
        )
        self.assertEqual(
            place(pool, {"a.example": 200, "b.example": 7}, 200), "b.example"
        )
        with self.assertRaisesRegex(
            AnsibleFilterError, "every zone of the pool is full"
        ):
            place(pool, {"a.example": 200, "b.example": 200}, 200)
        shared = {"cloudflare_zone_tokens": {"a.example": "t", "b.example": "t"}}
        with self.assertRaisesRegex(AnsibleFilterError, "share a token"):
            place(shared, {"a.example": 0, "b.example": 0}, 200)
        with self.assertRaisesRegex(AnsibleFilterError, "no record count"):
            place(pool, {"a.example": 0}, 200)
        with self.assertRaisesRegex(AnsibleFilterError, "names no zone"):
            place({"cloudflare_zone_tokens": ""}, {}, 200)


POOL = {
    "cloudflare_zone_tokens": json.dumps(
        {"a.example": "token-a", "b.example": "token-b"}
    )
}
SHARED = {"cloudflare_zone_tokens": json.dumps({"a.example": "t", "b.example": "t"})}
ZONE_IDS = {
    "a.example": "023e105f4ecef8ad9ca31a8372d0c353",
    "b.example": "9a7806061c88ada191ed06f989cc3dac",
}
LIMIT = 200
PLACEMENTS = (
    ({"a.example": 3, "b.example": 0}, "a.example"),
    ({"a.example": 200, "b.example": 7}, "b.example"),
)
FULL = {"a.example": 200, "b.example": 200}
PLACED_LINE = (
    'PLACED {"zone" : "b.example", "zone_id" : "9a7806061c88ada191ed06f989cc3dac"}'
)
MINT_TEMPLATE = "sql/project/prepare.sql.j2"
HINT_TEMPLATE = "sql/workspace/runner.sql.j2"


def jinja():
    """Returns:
    A native Jinja environment with the Ansible filters and tests and the
    filters of the role.
    """
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    for module in (CoreFilters(), MathFilters(), dns.FilterModule()):
        environment.filters.update(module.filters())
    environment.tests.update(CoreTests().tests())
    return environment


def render(expression, context):
    return jinja().from_string(expression).render(**context)


def holds(condition, context):
    return bool(jinja().compile_expression(condition)(**context))


def apply_tasks(name):
    return load_yaml_str(read_text(str(APPLY_DIR / f"{name}.yml")))


def setting(tasks, fact):
    """Args:
        tasks: a task list.
        fact: a fact a ``set_fact`` of the list sets.

    Returns:
        The first such ``set_fact`` task.
    """
    for task in tasks:
        if fact in task.get("ansible.builtin.set_fact", {}):
            return task
    raise AssertionError(f"no set_fact sets {fact}")


def counted(counts):
    """Args:
        counts: ``{zone: records}``.

    Returns:
        What the counting task of the cloudflare apply registers.
    """
    return {
        "results": [
            {
                "semaphore_cloudflare_zone_name": zone,
                "json": {"result_info": {"total_count": count}},
            }
            for zone, count in counts.items()
        ]
    }


def place(task, credentials, counts):
    """Args:
        task: the ``set_fact`` that places a new workspace.
        credentials: ``SEMAPHORE_DNS_CREDENTIALS``.
        counts: ``{zone: records}`` the zones hold.

    Returns:
        The ``workspace_dns`` the task sets.
    """
    context = {
        "SEMAPHORE_DNS_CREDENTIALS": credentials,
        "SEMAPHORE_DNS": {"record_limit": LIMIT},
        "semaphore_cloudflare_ids": ZONE_IDS,
        "semaphore_cloudflare_counts": counted(counts),
    }
    for name, expression in task.get("vars", {}).items():
        context[name] = render(expression, context)
    fact = task["ansible.builtin.set_fact"]["workspace_dns"]
    return {key: render(value, context) for key, value in fact.items()}


def placement_findings(task):
    """Args:
        task: the ``set_fact`` that places a new workspace.

    Returns:
        One message per pool state in which the task does not place the
        workspace in the first zone below the limit or does not refuse a
        full pool.
    """
    findings = []
    for counts, zone in PLACEMENTS:
        placed = place(task, POOL, counts)
        expected = {"zone": zone, "zone_id": ZONE_IDS[zone]}
        if placed != expected:
            findings.append(f"{counts} placed {placed}, expected {expected}")
    try:
        placed = place(task, POOL, FULL)
    except AnsibleFilterError as refusal:
        if "every zone of the pool is full" not in str(refusal):
            findings.append(f"a full pool refused with {refusal}")
    else:
        findings.append(f"a full pool placed {placed}")
    return findings


def held(tasks, lines, credentials):
    """Args:
        tasks: the cloudflare apply tasks.
        lines: the output lines of the hint query.
        credentials: ``SEMAPHORE_DNS_CREDENTIALS``.

    Returns:
        The facts the task that reads the pool and the placed zone sets.
    """
    context = {
        "SEMAPHORE_DNS_CREDENTIALS": credentials,
        "semaphore_workspace_alias": WORKSPACE,
        "semaphore_workspace_hint_query": {"stdout_lines": lines},
    }
    task = setting(tasks, "semaphore_workspace_placed")
    for name, expression in task["ansible.builtin.set_fact"].items():
        context[name] = render(expression, context)
    return context


def is_include(task, path):
    return str(task.get("ansible.builtin.include_tasks", "")).endswith(path)


def workspace_flow(tasks):
    """Args:
        tasks: ``tasks/workspace.yml``.

    Returns:
        The steps the operation runs in order, blocks unfolded, with
        ``tasks/utils/admin.yml`` inlined and the task files ``tasks`` hands it
        inlined in it.
    """
    flat = []
    for task in tasks:
        if "block" in task:
            flat += workspace_flow(task["block"])
            continue
        if not is_include(task, "tasks/utils/admin.yml"):
            flat.append(task)
            continue
        files = {
            f"{{{{ {name} }}}}": load_yaml_str(
                read_text(str(ROLE_DIR / path.removeprefix("{{ role_path }}/")))
            )
            for name, path in task["vars"].items()
        }
        for step in load_yaml_str(read_text(str(ADMIN_TASKS))):
            for inner in step.get("block", [step]):
                flat += files.get(inner.get("ansible.builtin.include_tasks"), [inner])
    return flat


def runs(task, context):
    when = task.get("when", [])
    return all(holds(c, context) for c in ([when] if isinstance(when, str) else when))


def order_findings(label, order, wanted):
    """Args:
        label: what the steps belong to.
        order: ``{step: index}`` of the steps found.
        wanted: the steps in the order they must run.

    Returns:
        One message when a step is missing or the steps run in another order.
    """
    missing = [step for step in wanted if step not in order]
    if missing:
        return [f"{label}: {missing} missing"]
    if [order[step] for step in wanted] != sorted(order.values()):
        return [f"{label}: run as {sorted(wanted, key=order.get)}"]
    return []


def flow_findings(tasks, steps):
    """Args:
        tasks: :func:`workspace_flow` of ``tasks/workspace.yml``.
        steps: ``tasks/utils/workspace/dns.yml``.

    Returns:
        One message per DNS flavor step that ``apply`` misses, runs under the
        wrong flavor or action, or runs after the admin token or the converge.
    """
    findings = []
    order = {}
    for index, task in enumerate(tasks):
        if is_include(task, "utils/workspace/dns.yml"):
            order["dns"] = index
            ran = [
                a for a in ("apply", "destroy") if runs(task, {"WORKSPACE_ACTION": a})
            ]
            if ran != ["apply"]:
                findings.append(f"the DNS steps run on {ran}")
        if HINT_TEMPLATE in str(task):
            order["hint"] = index
        if MINT_TEMPLATE in str(task):
            order["mint"] = index
        if "semaphore_workspace_spec" in (task.get("vars") or {}):
            order["converge"] = index
    inner = {}
    for index, task in enumerate(steps):
        for flavor in ("cloudflare", "route53"):
            if is_include(task, f"flavors/dns/workspace/{flavor}.yml"):
                inner[flavor] = index
                ran = [
                    f for f in dns.FLAVORS if runs(task, {"SEMAPHORE_DNS_FLAVOR": f})
                ]
                if ran != [flavor]:
                    findings.append(f"{flavor} runs under {ran}")
        if "workspace_dns is defined" in task.get("ansible.builtin.assert", {}).get(
            "that", []
        ):
            inner["zone"] = index
    findings += order_findings("the flow", order, ("hint", "dns", "mint", "converge"))
    findings += order_findings(
        "the DNS steps", inner, ("cloudflare", "route53", "zone")
    )
    return findings


def route53_findings(tasks):
    """Args:
        tasks: the route53 apply tasks.

    Returns:
        One message per way the tasks fail to render the workspace's policy
        through ``semaphore_route53_policy`` and to merge it, with a minted
        key, into the record ``credentials.json`` reads the route53 values
        from.
    """
    context = {
        "semaphore_workspace_alias": WORKSPACE,
        "workspace_dns": {"zone": SUBZONE, "zone_id": ZONE_ID},
    }
    task = setting(tasks, "semaphore_workspace_route53_policy")
    policy = render(
        task["ansible.builtin.set_fact"]["semaphore_workspace_route53_policy"], context
    )
    findings = []
    if policy != dns.semaphore_route53_policy(WORKSPACE, ZONE_ID, SUBZONE):
        findings.append(f"the policy is {policy}")
    mount, _, path = CREDENTIALS["dns"]["route53"]["path"].partition("/data/")
    writes = [
        t["vars"]
        for t in tasks
        if t.get("ansible.builtin.include_role", {}).get("tasks_from") == "utils/kv.yml"
    ]
    if [w["openbao_kv_state"] for w in writes] != ["read", "present"]:
        return [*findings, "the record is not read and then written"]
    for write in writes:
        target = (write["openbao_kv_mount"], render(write["openbao_kv_path"], context))
        if target != (mount, path.format(workspace=WORKSPACE)):
            findings.append(f"{write['openbao_kv_state']} goes to {target}")
    current = {KEY_FIELD: "AKIAWORKSPACE", SECRET_FIELD: "workspace-secret"}
    users = {
        "kept": (KEPT, {}),
        "minted": (MINTED, {KEY_FIELD: "AKIANEW", SECRET_FIELD: "new-secret"}),
    }
    for label, (user, key) in users.items():
        data = render(
            writes[-1]["openbao_kv_data"],
            {
                **context,
                "openbao_kv_current": current,
                "semaphore_route53_user": user,
                "semaphore_workspace_route53_policy": policy,
            },
        )
        if data != {**current, **key, "policy": policy}:
            findings.append(f"a {label} key leaves the record as {sorted(data)}")
    return findings


def route53_order_findings(tasks):
    """Args:
        tasks: the route53 apply tasks.

    Returns:
        One message when a route53 step is missing or runs out of order: the
        credential before the zone, the zone before the policy, the record
        read before the user takes its key, the user before the write.
    """
    order = {}
    for index, task in enumerate(tasks):
        fact = task.get("ansible.builtin.set_fact", {})
        state = (task.get("vars") or {}).get("openbao_kv_state")
        for step, found in (
            ("admin", is_include(task, "route53/admin.yml")),
            ("zone", "semaphore_route53_zone_info" in task),
            ("place", "workspace_dns" in fact),
            ("policy", "semaphore_workspace_route53_policy" in fact),
            ("read", state == "read"),
            ("user", "semaphore_route53_user" in task),
            ("write", state == "present"),
        ):
            if found:
                order[step] = index
    return order_findings("the route53 steps", order, ROUTE53_STEPS)


def user_findings(tasks):
    """Args:
        tasks: the route53 apply tasks.

    Returns:
        One message per way apply converges another user than ``ws-<id>``,
        with another policy than the rendered one, another credential than
        the workspace operation's, or a key the record does not hold with its
        secret.
    """
    (task,) = [t for t in tasks if "semaphore_route53_user" in t]
    args = task["semaphore_route53_user"]
    expected = {
        "user": "{{ semaphore_workspace_alias }}",
        "state": "present",
        "policy": "{{ semaphore_workspace_route53_policy }}",
        **ADMIN_ARGS,
    }
    findings = [
        f"{name} is {args.get(name)}"
        for name, value in expected.items()
        if args.get(name) != value
    ]
    for record, key in (
        ({KEY_FIELD: "AKIAWS", SECRET_FIELD: "s"}, "AKIAWS"),
        ({KEY_FIELD: "AKIAWS"}, ""),
        ({KEY_FIELD: "AKIAWS", SECRET_FIELD: ""}, ""),
        ({}, ""),
    ):
        held_key = render(args["held_access_key_id"], {"openbao_kv_current": record})
        if held_key != key:
            findings.append(f"{sorted(record)} holds the key {held_key!r}")
    return findings


def credential_task_findings(files):
    """Args:
        files: ``{label: tasks}`` of the route53 workspace steps.

    Returns:
        One message per task that runs a command, handles the AWS credential,
        the workspace key or the record without the masking idiom, or refuses
        with a hidden message or on a credential value.
    """
    findings = []
    for label, tasks in files.items():
        for task in tasks:
            name = task.get("name", "")
            if COMMANDS & set(task):
                findings.append(f"{label}: {name} runs a command")
            if INCLUDES & set(task):
                continue
            if "ansible.builtin.assert" in task:
                if "no_log" in task:
                    findings.append(f"{label}: {name} hides its message")
                if CREDENTIAL.search(str(task)):
                    findings.append(f"{label}: {name} asserts on a credential")
                continue
            if CREDENTIAL.search(str(task)) and task.get("no_log") != MASKED:
                findings.append(f"{label}: {name} handles a credential unmasked")
    return findings


def admin_findings(tasks):
    """Args:
        tasks: ``route53/admin.yml``.

    Returns:
        One message per way the step reads the AWS credential elsewhere than
        the deploy writes it, admits a record that lacks a field, refuses a
        complete one, or refuses without naming the path and the field.
    """
    findings = []
    (read,) = [
        t["vars"]
        for t in tasks
        if t.get("ansible.builtin.include_role", {}).get("tasks_from") == "utils/kv.yml"
    ]
    target = (read["openbao_kv_mount"], read["openbao_kv_path"])
    if read["openbao_kv_state"] != "read" or target != dns.ROUTE53_ADMIN:
        findings.append(f"the credential is read from {target}")
    hold = setting(tasks, "semaphore_route53_admin_missing")
    guard = next(t for t in tasks if "ansible.builtin.assert" in t)
    if "no_log" in guard:
        findings.append("the refusal hides its message")
    full = dict.fromkeys(dns.ROUTE53_FIELDS, "value")
    for record, refused in (
        ({}, True),
        ({"access_key_id": "AKIA"}, True),
        ({**full, "secret_access_key": ""}, True),
        (full, False),
    ):
        context = {"openbao_kv_current": record, "semaphore_workspace_alias": WORKSPACE}
        for name, expression in hold["ansible.builtin.set_fact"].items():
            context[name] = render(expression, context)
        passed = all(holds(c, context) for c in guard["ansible.builtin.assert"]["that"])
        if passed == refused:
            findings.append(f"{sorted(record)} {'passes' if passed else 'is refused'}")
            continue
        message = render(guard["ansible.builtin.assert"]["fail_msg"], context)
        named = [ADMIN_PATH, *context["semaphore_route53_admin_missing"]]
        if refused and any(part not in message for part in named):
            findings.append(f"{sorted(record)} is refused without naming {named}")
    return findings


def destroy_findings(tasks, steps):
    """Args:
        tasks: :func:`workspace_flow` of ``tasks/workspace.yml``.
        steps: ``route53/destroy.yml``.

    Returns:
        One message per way destroy misses the IAM user of the workspace,
        runs its removal under another action or flavor, or removes it with
        another credential than the workspace operation's.
    """
    includes = [t for t in tasks if is_include(t, "workspace/route53/destroy.yml")]
    if len(includes) != 1:
        return [f"workspace.yml includes the route53 destroy {len(includes)} times"]
    findings = []
    ran = [
        (action, flavor)
        for action in ("apply", "destroy")
        for flavor in dns.FLAVORS
        if runs(
            includes[0], {"WORKSPACE_ACTION": action, "SEMAPHORE_DNS_FLAVOR": flavor}
        )
    ]
    if ran != [("destroy", "route53")]:
        findings.append(f"the route53 destroy runs on {ran}")
    if not is_include(steps[0], "route53/admin.yml"):
        findings.append("destroy reads no AWS credential first")
    removals = [
        t["semaphore_route53_user"] for t in steps if "semaphore_route53_user" in t
    ]
    expected = {
        "user": "{{ semaphore_workspace_alias }}",
        "state": "absent",
        **ADMIN_ARGS,
    }
    if removals != [expected]:
        findings.append(f"destroy calls {removals}")
    return findings


class TestCloudflareApply(unittest.TestCase):
    def setUp(self):
        self.tasks = apply_tasks("cloudflare")
        self.placement = setting(apply_tasks("cloudflare/place"), "workspace_dns")

    def test_apply_places_a_new_workspace_through_the_filter(self):
        self.assertIn("| semaphore_cloudflare_zone(", str(self.placement["vars"]))
        self.assertEqual(placement_findings(self.placement), [])
        self.assertEqual(list(dns.semaphore_cloudflare_pool(POOL)), list(ZONE_IDS))

    def test_apply_refuses_a_pool_with_a_shared_token(self):
        with self.assertRaisesRegex(AnsibleFilterError, "share a token"):
            place(self.placement, SHARED, {"a.example": 0, "b.example": 0})
        with self.assertRaisesRegex(AnsibleFilterError, "share a token"):
            held(self.tasks, [], SHARED)

    def test_negative_control_a_placement_past_the_filter_fails(self):
        planted = copy.deepcopy(self.placement)
        planted["vars"]["semaphore_workspace_zone"] = (
            "{{ semaphore_cloudflare_records | list | first }}"
        )
        first = {"zone": "a.example", "zone_id": ZONE_IDS["a.example"]}
        second = {"zone": "b.example", "zone_id": ZONE_IDS["b.example"]}
        self.assertEqual(
            placement_findings(planted),
            [
                f"{PLACEMENTS[1][0]} placed {first}, expected {second}",
                f"a full pool placed {first}",
            ],
        )

    def test_apply_keeps_a_placed_workspace_in_its_zone(self):
        facts = held(self.tasks, ["HINT 12", PLACED_LINE], POOL)
        keep = setting(self.tasks, "workspace_dns")
        self.assertTrue(holds(keep["when"], facts))
        self.assertEqual(
            render(keep["ansible.builtin.set_fact"]["workspace_dns"], facts),
            {"zone": "b.example", "zone_id": ZONE_IDS["b.example"]},
        )
        new = next(t for t in self.tasks if is_include(t, "cloudflare/place.yml"))
        self.assertFalse(holds(new["when"], facts))
        self.assertTrue(holds(new["when"], held(self.tasks, ["HINT 12"], POOL)))

    def test_apply_refuses_to_move_a_workspace_whose_zone_left_the_pool(self):
        guard = next(
            t
            for t in self.tasks
            if "semaphore_workspace_placed" in str(t.get("ansible.builtin.assert"))
        )
        (condition,) = guard["ansible.builtin.assert"]["that"]
        self.assertTrue(holds(condition, held(self.tasks, [PLACED_LINE], POOL)))
        moved = PLACED_LINE.replace("b.example", "c.example")
        self.assertFalse(holds(condition, held(self.tasks, [moved], POOL)))

    def test_the_hint_query_reads_the_placed_zone_under_cloudflare_only(self):
        template = jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            autoescape=jinja2.select_autoescape(default_for_string=False),
        ).from_string(read_text(str(RUNNER_SQL)))
        rendered = {
            flavor: template.render(
                semaphore_workspace_runner_action="hint",
                semaphore_workspace_alias=WORKSPACE,
                SEMAPHORE_DNS_FLAVOR=flavor,
                SEMAPHORE_PROVISION_PROJECT_NAME=PROVISION,
            )
            for flavor in dns.FLAVORS
        }
        self.assertEqual(
            [f for f, sql in rendered.items() if "SELECT 'PLACED ' ||" in sql],
            ["cloudflare"],
        )
        self.assertIn(
            "'zone', held.env::json ->> 'WORKSPACE_DNS_ZONE'", rendered["cloudflare"]
        )
        self.assertIn(
            "'zone_id', held.env::json ->> 'WORKSPACE_DNS_ZONE_ID'",
            rendered["cloudflare"],
        )


class TestApplyFlow(unittest.TestCase):
    def setUp(self):
        self.tasks = workspace_flow(load_yaml_str(read_text(str(WORKSPACE_TASKS))))
        self.steps = load_yaml_str(read_text(str(DNS_STEPS)))

    def test_apply_runs_each_dns_flavor_step_before_the_token_and_the_converge(self):
        self.assertEqual(flow_findings(self.tasks, self.steps), [])

    def test_negative_control_a_dropped_placement_fails(self):
        planted = [
            t
            for t in self.steps
            if not is_include(t, "flavors/dns/workspace/cloudflare.yml")
        ]
        self.assertEqual(
            flow_findings(self.tasks, planted),
            ["the DNS steps: ['cloudflare'] missing"],
        )

    def test_negative_control_a_placement_after_the_token_fails(self):
        planted = copy.deepcopy(self.tasks)
        step = next(t for t in planted if is_include(t, "utils/workspace/dns.yml"))
        planted.remove(step)
        planted.append(step)
        steps = ["hint", "mint", "converge", "dns"]
        self.assertEqual(
            flow_findings(planted, self.steps), [f"the flow: run as {steps}"]
        )

    def test_negative_control_a_step_under_another_flavor_fails(self):
        planted = copy.deepcopy(self.steps)
        step = next(
            t for t in planted if is_include(t, "flavors/dns/workspace/cloudflare.yml")
        )
        step["when"] = "SEMAPHORE_DNS_FLAVOR != 'knot'"
        self.assertEqual(
            flow_findings(self.tasks, planted),
            ["cloudflare runs under ['cloudflare', 'route53']"],
        )

    def test_negative_control_route53_after_the_zone_check_fails(self):
        planted = copy.deepcopy(self.steps)
        step = next(
            t for t in planted if is_include(t, "flavors/dns/workspace/route53.yml")
        )
        planted.remove(step)
        planted.append(step)
        self.assertEqual(
            flow_findings(self.tasks, planted),
            ["the DNS steps: run as ['cloudflare', 'zone', 'route53']"],
        )


class TestRoute53Apply(unittest.TestCase):
    def setUp(self):
        self.tasks = apply_tasks("route53")

    def test_apply_hands_the_route53_policy_to_the_workspace_record(self):
        self.assertEqual(route53_findings(self.tasks), [])

    def test_negative_control_a_policy_past_the_filter_fails(self):
        planted = copy.deepcopy(self.tasks)
        task = setting(planted, "semaphore_workspace_route53_policy")
        task["ansible.builtin.set_fact"]["semaphore_workspace_route53_policy"] = (
            "{{ {'Version': '2012-10-17', 'Statement': []} }}"
        )
        self.assertEqual(
            route53_findings(planted),
            ["the policy is {'Version': '2012-10-17', 'Statement': []}"],
        )

    def test_negative_control_a_write_that_drops_the_access_key_fails(self):
        planted = copy.deepcopy(self.tasks)
        planted[-1]["vars"]["openbao_kv_data"] = (
            "{{ {'policy': semaphore_workspace_route53_policy} }}"
        )
        self.assertEqual(
            route53_findings(planted),
            [
                "a kept key leaves the record as ['policy']",
                "a minted key leaves the record as ['policy']",
            ],
        )

    def test_apply_reads_the_credential_then_the_zone_then_the_record_then_the_user(
        self,
    ):
        self.assertEqual(route53_order_findings(self.tasks), [])

    def test_negative_control_a_user_before_the_record_read_fails(self):
        planted = copy.deepcopy(self.tasks)
        read = next(
            t
            for t in planted
            if (t.get("vars") or {}).get("openbao_kv_state") == "read"
        )
        planted.remove(read)
        planted.insert(len(planted) - 1, read)
        self.assertEqual(
            route53_order_findings(planted),
            [
                (
                    "the route53 steps: run as "
                    "['admin', 'zone', 'place', 'policy', 'user', 'read', 'write']"
                )
            ],
        )

    def test_apply_places_the_workspace_in_the_hosted_zone_it_finds(self):
        (lookup,) = [t for t in self.tasks if "semaphore_route53_zone_info" in t]
        self.assertEqual(
            lookup["semaphore_route53_zone_info"],
            {"zone": "{{ SEMAPHORE_DNS.zone }}", **ADMIN_ARGS},
        )
        fact = setting(self.tasks, "workspace_dns")["ansible.builtin.set_fact"]
        context = {
            "SEMAPHORE_DNS": {"zone": SUBZONE},
            "semaphore_route53_zone": {"zone": SUBZONE, "zone_id": ZONE_ID},
        }
        self.assertEqual(
            {k: render(v, context) for k, v in fact["workspace_dns"].items()},
            {"zone": SUBZONE, "zone_id": ZONE_ID},
        )

    def test_apply_converges_the_user_with_its_policy_and_the_held_key(self):
        self.assertEqual(user_findings(self.tasks), [])

    def test_negative_control_a_key_held_without_its_secret_fails(self):
        planted = copy.deepcopy(self.tasks)
        task = next(t for t in planted if "semaphore_route53_user" in t)
        task["semaphore_route53_user"]["held_access_key_id"] = (
            "{{ openbao_kv_current.get('access_key', '') }}"
        )
        self.assertEqual(
            user_findings(planted),
            [
                "['access_key'] holds the key 'AKIAWS'",
                "['access_key', 'secret_key'] holds the key 'AKIAWS'",
            ],
        )

    def test_a_second_apply_writes_no_record(self):
        write = next(
            t
            for t in KV_UTIL
            if "openbao_kv_data"
            in str((t.get("ansible.builtin.shell") or {}).get("stdin"))
        )
        policy = dns.semaphore_route53_policy(WORKSPACE, ZONE_ID, SUBZONE)
        held_record = {KEY_FIELD: "AKIAWORKSPACE", SECRET_FIELD: "s", "policy": policy}
        expression = self.tasks[-1]["vars"]["openbao_kv_data"]
        for user, written in ((KEPT, False), (MINTED, True)):
            context = {
                "openbao_kv_state": "present",
                "openbao_kv_current": held_record,
                "semaphore_route53_user": user,
                "semaphore_workspace_route53_policy": policy,
            }
            context["openbao_kv_data"] = render(expression, context)
            with self.subTest(minted=user["minted"]):
                self.assertIs(runs(write, context), written)

    def test_a_minted_key_needs_its_secret(self):
        with self.assertRaisesRegex(AnsibleFilterError, "without its id or secret"):
            dns.semaphore_route53_record({}, {**MINTED, "secret_access_key": None}, {})

    def test_every_task_that_handles_the_aws_credential_is_masked(self):
        self.assertEqual(credential_task_findings(route53_files()), [])

    def test_negative_control_an_unmasked_or_command_line_credential_fails(self):
        files = route53_files()
        user = next(t for t in files["route53"] if "semaphore_route53_user" in t)
        user.pop("no_log")
        files["route53/destroy"].append(
            {
                "name": "aws",
                "ansible.builtin.shell": (
                    "aws iam delete-user {{ semaphore_route53_admin.secret_access_key }}"
                ),
                "no_log": MASKED,
            }
        )
        guard = next(t for t in files["route53/admin"] if "ansible.builtin.assert" in t)
        guard["no_log"] = MASKED
        self.assertEqual(
            credential_task_findings(files),
            [
                f"route53: {user['name']} handles a credential unmasked",
                f"route53/admin: {guard['name']} hides its message",
                "route53/destroy: aws runs a command",
            ],
        )

    def test_apply_and_destroy_refuse_a_missing_aws_credential_by_its_path(self):
        self.assertEqual(admin_findings(route53_files()["route53/admin"]), [])
        self.assertEqual(
            dns.semaphore_route53_admin_missing({}), list(dns.ROUTE53_FIELDS)
        )

    def test_negative_control_a_credential_check_that_skips_fails(self):
        tasks = route53_files()["route53/admin"]
        guard = next(t for t in tasks if "ansible.builtin.assert" in t)
        guard["ansible.builtin.assert"]["that"] = ["true"]
        read = next(t for t in tasks if "vars" in t)
        read["vars"]["openbao_kv_path"] = "provision/route53"
        self.assertEqual(
            admin_findings(tasks),
            [
                "the credential is read from ('platform', 'provision/route53')",
                "[] passes",
                "['access_key_id'] passes",
                "['access_key_id', 'secret_access_key'] passes",
            ],
        )

    def test_destroy_removes_the_iam_user_under_route53_only(self):
        tasks = workspace_flow(load_yaml_str(read_text(str(WORKSPACE_TASKS))))
        steps = route53_files()["route53/destroy"]
        self.assertEqual(destroy_findings(tasks, steps), [])

    def test_negative_control_a_removal_on_apply_or_without_the_credential_fails(self):
        tasks = workspace_flow(load_yaml_str(read_text(str(WORKSPACE_TASKS))))
        step = next(t for t in tasks if is_include(t, "workspace/route53/destroy.yml"))
        step["when"] = "SEMAPHORE_DNS_FLAVOR == 'route53'"
        steps = route53_files()["route53/destroy"][1:]
        self.assertEqual(
            destroy_findings(tasks, steps),
            [
                "the route53 destroy runs on [('apply', 'route53'), ('destroy', 'route53')]",
                "destroy reads no AWS credential first",
            ],
        )


def route53_files():
    """Returns:
    ``{label: tasks}`` of ``route53.yml``, ``route53/admin.yml`` and
    ``route53/destroy.yml``.
    """
    return {
        name: apply_tasks(name)
        for name in ("route53", "route53/admin", "route53/destroy")
    }


def provision_environment(workspace_dns):
    """Args:
    workspace_dns: the ``workspace_dns`` fact a DNS flavor set.

    Returns:
        The provision environment ``tasks/workspace.yml`` hands ``apply``.
    """
    return {
        "WORKSPACE": ALIAS,
        "WORKSPACE_DNS_ZONE": workspace_dns["zone"],
        "WORKSPACE_DNS_ZONE_ID": workspace_dns["zone_id"],
        "WORKSPACE_TARGETS": "203.0.113.10:22",
    }


def held_values(api):
    """Args:
    api: the fake after a workspace apply.

    Returns:
        ``{template: (WORKSPACE, WORKSPACE_DNS_ZONE, WORKSPACE_DNS_ZONE_ID)}`` of
        the environment each provision template of the workspace runs with.
    """
    project_id = api.project_id(PROVISION)
    environments = {
        e["id"]: decoded(e) for e in api.objects[(project_id, "environment")]
    }
    templates = api.templates(project_id)
    held = {}
    for name in TEMPLATES:
        env = environments[templates[f"{name} {ALIAS}"]["environment_id"]]
        held[name] = (
            env["WORKSPACE"],
            env["WORKSPACE_DNS_ZONE"],
            env["WORKSPACE_DNS_ZONE_ID"],
        )
    return held


def apply_under(mod, workspace_dns):
    """Args:
    mod: the converger module.
    workspace_dns: the ``workspace_dns`` fact a DNS flavor set.

    Returns:
        The fake after a platform converge and a workspace apply.
    """
    api = FakeSemaphore(mod.ApiError)
    mod.converge(api, platform_spec(), lambda seconds: None)
    spec = workspace_spec()
    spec["provision"]["environment"] = provision_environment(workspace_dns)
    mod.run_workspace(api, spec, lambda seconds: None)
    return api


class TestWorkspaceValues(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()

    def test_apply_writes_the_workspace_values_per_flavor(self):
        for flavor, workspace_dns in FLAVOR_VALUES.items():
            with self.subTest(flavor):
                expected = (ALIAS, workspace_dns["zone"], workspace_dns["zone_id"])
                self.assertEqual(
                    held_values(apply_under(self.mod, workspace_dns)),
                    dict.fromkeys(TEMPLATES, expected),
                )
        self.assertEqual(
            [f for f, d in FLAVOR_VALUES.items() if not d["zone_id"]], ["knot"]
        )

    def test_the_operation_takes_the_values_from_the_flavor_fact_only(self):
        tasks = workspace_flow(load_yaml_str(read_text(str(WORKSPACE_TASKS))))
        converge = next(
            t for t in tasks if "semaphore_workspace_spec" in t.get("vars", {})
        )
        environment = converge["vars"]["semaphore_workspace_provision_values"]
        self.assertEqual(environment["WORKSPACE"], "{{ semaphore_workspace_alias }}")
        self.assertIn("workspace_dns.zone ", environment["WORKSPACE_DNS_ZONE"])
        self.assertIn("workspace_dns.zone_id ", environment["WORKSPACE_DNS_ZONE_ID"])

    def test_negative_control_a_second_apply_under_another_zone_moves_every_template(
        self,
    ):
        api = apply_under(self.mod, FLAVOR_VALUES["route53"])
        spec = workspace_spec()
        spec["provision"]["environment"] = provision_environment(
            FLAVOR_VALUES["cloudflare"]
        )
        self.mod.run_workspace(api, spec, lambda seconds: None)
        self.assertEqual(
            set(held_values(api).values()),
            {(ALIAS, "example.com", FLAVOR_VALUES["cloudflare"]["zone_id"])},
        )


if __name__ == "__main__":
    unittest.main()
