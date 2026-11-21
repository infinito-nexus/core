import json
import unittest

from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.seaweedfs import seaweedfs_s3_identities
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

TEMPLATES = PROJECT_ROOT / "roles" / "web-svc-seaweedfs" / "templates"
TEMPLATE = "s3.json.j2"
VARS = load_yaml_str(
    read_text(str(PROJECT_ROOT / "roles" / "web-svc-seaweedfs" / ROLE_FILE_VARS_MAIN))
)
SEMAPHORE = PROJECT_ROOT / "roles" / "web-app-semaphore"
SEMAPHORE_VARS = load_yaml_str(read_text(str(SEMAPHORE / ROLE_FILE_VARS_MAIN)))
SEMAPHORE_SECRETS = load_yaml_str(read_text(str(SEMAPHORE / ROLE_FILE_META_SECRETS)))
EXPORT_PY = SEMAPHORE / "files" / "python" / "export.py"
EXPORT_TASK_PY = SEMAPHORE / "files" / "python" / "export_task.py"
EXPORT_BLOCK = """         "Read:" ~ SEAWEEDFS_EXPORT.bucket,
         "Write:" ~ SEAWEEDFS_EXPORT.bucket,
         "List:" ~ SEAWEEDFS_EXPORT.bucket
"""
EXPORT_KEYS = {"access_key": "EXPORTAK", "secret_key": "export-sk"}
WORKSPACE = "0b5e8c1e-6f43-4c3a-9d6b-2a1f0e9c7d11"
ADMIN_BLOCK = """{% set _ = identities.append({
  "name": "admin",
  "credentials": [{"accessKey": SEAWEEDFS_ADMIN_ACCESS_KEY, "secretKey": SEAWEEDFS_ADMIN_SECRET_KEY}],
  "actions": ["Admin", "Read", "Write", "List", "Tagging"]
}) %}
"""
CONSUMERS = {
    "web-app-nextcloud": {
        "bucket": "nextcloud",
        "access_key": "nc-ak",
        "secret_key": "nc-sk",
        "public": False,
    },
    "web-app-pixelfed": {
        "bucket": "pixelfed",
        "access_key": "px-ak",
        "secret_key": "px-sk",
        "public": True,
    },
}


def _environment(consumers):
    def lookup(name, *terms):
        if name == "objstore_consumers":
            return list(consumers)
        if name == "objstore":
            return consumers[terms[0]]
        raise AssertionError(f"unexpected lookup {name}")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.globals["lookup"] = lookup
    env.filters["seaweedfs_s3_identities"] = seaweedfs_s3_identities
    env.filters["bool"] = to_bool
    env.filters["to_nice_json"] = lambda value: json.dumps(
        value, indent=4, sort_keys=True
    )
    return env


def _export(enabled):
    """Args:
    enabled: whether the export runner of web-app-semaphore runs.

    Returns:
        ``SEAWEEDFS_EXPORT`` of ``vars/main.yml`` with its lookups answered.
    """
    return {
        **VARS["SEAWEEDFS_EXPORT"],
        "enabled": enabled,
        **EXPORT_KEYS,
    }


def _variables(records, export=False):
    return {
        "SEAWEEDFS_ADMIN_ACCESS_KEY": "administrator",
        "SEAWEEDFS_ADMIN_SECRET_KEY": "admin-secret",
        "SEAWEEDFS_EXPORT": _export(export),
        "seaweedfs_workspace_records": records,
    }


def _render(consumers, records, export=False, source=None):
    environment = _environment(consumers)
    template = (
        environment.get_template(TEMPLATE)
        if source is None
        else environment.from_string(source)
    )
    return json.loads(template.render(**_variables(records, export)))["identities"]


def _record():
    return {"workspace": WORKSPACE, "access_key": "WSAK", "secret_key": "wssk"}


def export_findings(identities):
    """Args:
    identities: the rendered ``s3.json`` identities.

    Returns:
        Why the identity ``export`` holds more or less than ``Read``, ``Write``
        and ``List`` on the bucket ``exports``, or another identity reaches it.
    """
    bucket = VARS["SEAWEEDFS_EXPORT"]["bucket"]
    named = [i for i in identities if i["name"] == VARS["SEAWEEDFS_EXPORT"]["identity"]]
    if len(named) != 1:
        return [f"{len(named)} identities are named export"]
    findings = []
    expected = [f"{action}:{bucket}" for action in ("Read", "Write", "List")]
    if named[0]["actions"] != expected:
        findings.append(f"export holds {named[0]['actions']}")
    if named[0]["credentials"] != [
        {"accessKey": EXPORT_KEYS["access_key"], "secretKey": EXPORT_KEYS["secret_key"]}
    ]:
        findings.append("export does not hold the keys of its owner")
    findings += [
        f"{i['name']} reaches {bucket}"
        for i in identities
        if i is not named[0]
        and any(action.endswith(f":{bucket}") for action in i.get("actions", []))
    ]
    return findings


class TestS3Identities(unittest.TestCase):
    def test_the_planted_admin_block_matches_the_template(self):
        self.assertIn(ADMIN_BLOCK, read_text(str(TEMPLATES / TEMPLATE)))

    def test_a_workspace_identity_holds_three_actions_on_its_bucket(self):
        identities = _render(CONSUMERS, [_record()])
        (workspace,) = [
            identity
            for identity in identities
            if identity["name"] == f"ws-{WORKSPACE}-provision"
        ]
        bucket = f"ws-{WORKSPACE}-state"
        self.assertEqual(
            workspace["actions"],
            [f"Read:{bucket}", f"Write:{bucket}", f"List:{bucket}"],
        )
        self.assertEqual(
            workspace["credentials"], [{"accessKey": "WSAK", "secretKey": "wssk"}]
        )

    def test_no_other_identity_reaches_a_workspace_bucket(self):
        identities = _render(CONSUMERS, [_record()])
        reaching = [
            identity["name"]
            for identity in identities
            if any(
                action.endswith(f":ws-{WORKSPACE}-state")
                for action in identity.get("actions", [])
            )
        ]
        self.assertEqual(reaching, [f"ws-{WORKSPACE}-provision"])

    def test_the_assembly_always_holds_the_admin(self):
        for consumers, records in (
            ({}, []),
            (CONSUMERS, []),
            ({}, [_record()]),
            (CONSUMERS, [_record()]),
        ):
            with self.subTest(consumers=list(consumers), records=len(records)):
                identities = _render(consumers, records)
                (admin,) = [i for i in identities if i["name"] == "admin"]
                self.assertIn("Admin", admin["actions"])
                self.assertEqual(
                    admin["credentials"],
                    [{"accessKey": "administrator", "secretKey": "admin-secret"}],
                )

    def test_the_export_identity_holds_three_actions(self):
        for consumers, records in ((CONSUMERS, [_record()]), ({}, [])):
            with self.subTest(consumers=list(consumers), records=len(records)):
                identities = _render(consumers, records, export=True)
                self.assertEqual(export_findings(identities), [])
        export = VARS["SEAWEEDFS_EXPORT"]
        self.assertEqual((export["identity"], export["bucket"]), ("export", "exports"))
        self.assertIn(
            f'\nBUCKET = "{export["bucket"]}"\n', read_text(str(EXPORT_TASK_PY))
        )
        self.assertIn("{self.bucket_url()}/ws-", read_text(str(EXPORT_PY)))

    def test_the_export_identity_takes_the_keys_semaphore_hands_to_openbao(self):
        export = VARS["SEAWEEDFS_EXPORT"]
        login = SEMAPHORE_VARS["SEMAPHORE_EXPORT_S3_LOGIN"]
        self.assertEqual(VARS["SEAWEEDFS_EXPORT_OWNER"], "web-app-semaphore")
        self.assertEqual((login["mount"], login["path"]), ("platform", "export/s3"))
        task = read_text(str(EXPORT_TASK_PY))
        self.assertIn(f'\nPLATFORM_MOUNT = "{login["mount"]}"\n', task)
        self.assertIn(f'\nS3_LOGIN_PATH = "{login["path"]}"\n', task)
        self.assertIn("read_all(PLATFORM_MOUNT, S3_LOGIN_PATH)", task)
        for field in ("access_key", "secret_key"):
            with self.subTest(field=field):
                credential = f"secrets.credentials.export_s3_{field}"
                self.assertIn(credential, export[field])
                self.assertIn("SEAWEEDFS_EXPORT_OWNER", export[field])
                self.assertIn(credential, login["data"][field])
                self.assertIn(f"export_s3_{field}", SEMAPHORE_SECRETS["credentials"])
        self.assertIn("services.export-runner.enabled", export["enabled"])

    def test_no_export_identity_without_the_export_runner(self):
        names = [identity["name"] for identity in _render(CONSUMERS, [_record()])]
        self.assertNotIn(VARS["SEAWEEDFS_EXPORT"]["identity"], names)

    def test_negative_control_an_export_identity_with_consumer_actions_fails(self):
        source = read_text(str(TEMPLATES / TEMPLATE))
        self.assertIn(EXPORT_BLOCK, source)
        planted = source.replace(
            EXPORT_BLOCK,
            EXPORT_BLOCK.rstrip("\n")
            + ',\n         "WriteAcp:" ~ SEAWEEDFS_EXPORT.bucket,'
            + '\n         "Tagging:" ~ SEAWEEDFS_EXPORT.bucket\n',
        )
        findings = export_findings(
            _render(CONSUMERS, [_record()], export=True, source=planted)
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("WriteAcp:exports", findings[0])

    def test_negative_control_a_template_without_the_export_identity_fails(self):
        source = read_text(str(TEMPLATES / TEMPLATE))
        start = source.index("{% if SEAWEEDFS_EXPORT.enabled | bool %}")
        end = source.index("{% endif %}", start) + len("{% endif %}\n")
        planted = source[:start] + source[end:]
        self.assertEqual(
            export_findings(_render(CONSUMERS, [], export=True, source=planted)),
            ["0 identities are named export"],
        )

    def test_negative_control_a_consumer_on_the_exports_bucket_fails(self):
        consumers = {
            **CONSUMERS,
            "web-app-exports": {
                "bucket": VARS["SEAWEEDFS_EXPORT"]["bucket"],
                "access_key": "ex-ak",
                "secret_key": "ex-sk",
                "public": False,
            },
        }
        self.assertEqual(
            export_findings(_render(consumers, [], export=True)),
            ["web-app-exports reaches exports"],
        )

    def test_an_assembly_without_the_admin_fails(self):
        planted = read_text(str(TEMPLATES / TEMPLATE)).replace(ADMIN_BLOCK, "")
        template = _environment(CONSUMERS).from_string(planted)
        for records in ([], [_record()]):
            with (
                self.subTest(records=len(records)),
                self.assertRaises(AnsibleFilterError),
            ):
                template.render(**_variables(records))


if __name__ == "__main__":
    unittest.main()
