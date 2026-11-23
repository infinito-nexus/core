import base64
import contextlib
import io
import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_any

from . import PROJECT_ROOT

USER_LDAP_ADDON = (
    PROJECT_ROOT / "roles" / "web-app-nextcloud" / "meta" / "addons" / "user_ldap.yml"
)
SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-nextcloud"
    / "files"
    / "python"
    / "ldap_refresh.py"
)
TASKS = (
    PROJECT_ROOT
    / "roles"
    / "web-app-nextcloud"
    / "tasks"
    / "utils"
    / "ldap_refresh.yml"
)
MAPPING = (
    PROJECT_ROOT
    / "roles"
    / "web-app-nextcloud"
    / "files"
    / "php"
    / "utils"
    / "ldap_user_mapping.php"
)
PHP = [
    "/usr/bin/container",
    "exec",
    "-i",
    "--user",
    "www-data",
    "c1",
    "php",
]
PREFIX = [*PHP, "/var/www/html/occ"]
MAPPING_CALL = [*PHP, "--", "/var/www/html"]
PARTS = ["street", "postalCode", "l", "st", "c"]


def load_module(hook_dir):
    """Load the hook as the runner stages it, with its mapping program beside it.

    Args:
        hook_dir: the directory the runner writes the script and its modules to.
    """
    (hook_dir / MAPPING.name).write_text(read_text(str(MAPPING)), encoding="utf-8")
    module = types.ModuleType("nextcloud_ldap_refresh")
    module.__file__ = str(hook_dir / "main.py")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class FakeNextcloud:
    """A Nextcloud whose ``ldap:check-user`` fails on an account ``user_ldap`` did not map.

    Args:
        mapping: ``{directory uuid: Nextcloud account}`` of ``ldap_user_mapping``.
        addresses: the profile address of each account.
        script: the mapping script the hook has to pipe into ``php``.
        directory: ``{directory uuid: Nextcloud account}`` that ``user_ldap`` maps
            when ``user:list`` enumerates the directory.
    """

    def __init__(self, mapping, addresses, script, directory):
        self.mapping = dict(mapping)
        self.addresses = dict(addresses)
        self.script = script
        self.directory = directory
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv == MAPPING_CALL:
            stdout = ""
            if kwargs.get("input") == self.script:
                stdout = f"booting\nLDAP_MAPPING {json.dumps(self.mapping)}\n"
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        args = argv[len(PREFIX) :]
        stdout = ""
        if args[0] == "user:list":
            self.mapping.update(self.directory)
            stdout = json.dumps(dict.fromkeys(self.mapping.values(), ""))
        if args[0] == "ldap:check-user" and args[2] not in self.mapping.values():
            raise subprocess.CalledProcessError(
                1, argv, output="The given user is not a recognized LDAP user."
            )
        if args[0] == "user:profile" and args[3].startswith("--default-value"):
            stdout = self.addresses.get(args[1], "") + "\n"
        elif args[0] == "user:profile":
            self.addresses[args[1]] = args[3]
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def member(username, **parts):
    """Return one ``@users`` member as the runner hands it over.

    Args:
        username: the login; the member's uuid is ``uuid-<login>``.
        parts: address attribute values by attribute name; absent ones are empty.
    """
    return {
        "username": username,
        "email": "",
        "name": "",
        "uuid": f"uuid-{username}",
        "attributes": {
            part: base64.b64encode(parts.get(part, "").encode()).decode()
            for part in PARTS
        },
    }


def mapped(*usernames):
    return {f"uuid-{username}": username for username in usernames}


def address_mapping(addon):
    """Return the directory attribute ``user_ldap`` maps onto the profile address.

    Args:
        addon: the parsed ``user_ldap`` addon definition.
    """
    [value] = [
        entry["configvalue"]
        for entry in addon["config"]["plugin_configuration"]
        if entry["configkey"].endswith("}}ldap_attr_address")
    ]
    return value


def leaves_a_street_only_address(addon, include):
    """Args:
        addon: the parsed ``user_ldap`` addon definition.
        include: the vars the role hands the RBAC hook.

    Returns:
        Whether a refresh ``user_ldap`` runs on its own can leave the street alone in
        the address for longer than one timer interval: ``user_ldap`` maps the
        address while the timer may skip the hook that composes it.
    """
    return (
        bool(address_mapping(addon))
        and include["rbac_sync_skip_unchanged"] is not False
    )


class NextcloudLdapRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mod = load_module(Path(self.tmp.name))
        self.script = read_text(str(MAPPING))
        self.members_file = Path(self.tmp.name) / "members.json"

    def environ(self, members, listing=True):
        self.members_file.write_text(json.dumps({"@users": members}))
        return {
            "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
            "RBAC_SYNC_CID": "c1",
            "RBAC_SYNC_MEMBERS_FILE": str(self.members_file),
            "NEXTCLOUD_USER": "www-data",
            "NEXTCLOUD_OCC": "/var/www/html/occ",
            "NEXTCLOUD_ADDRESS_ATTRIBUTES": json.dumps(PARTS),
            "NEXTCLOUD_LDAP_USER_LISTING": "true" if listing else "false",
        }

    def run_main(self, mapping, members, addresses=None, directory=None, listing=True):
        nextcloud = FakeNextcloud(
            mapping, addresses or {}, self.script, directory or {}
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.mod.main(self.environ(members, listing), run=nextcloud)
        self.code = code
        self.stderr = stderr.getvalue().strip().splitlines()
        return nextcloud, stdout.getvalue().strip().splitlines()

    def test_only_accounts_user_ldap_mapped_are_refreshed(self):
        nextcloud, output = self.run_main(
            mapped("alice", "bob"),
            [member("bob"), member("alice"), member("carol")],
        )

        self.assertEqual(
            [call for call in nextcloud.calls if "user:profile" not in call],
            [
                [*PREFIX, "user:list", "--output=json", "--limit=0"],
                MAPPING_CALL,
                [*PREFIX, "ldap:check-user", "--update", "alice"],
                [*PREFIX, "ldap:check-user", "--update", "bob"],
            ],
        )
        self.assertEqual((self.code, output), (0, ["REFRESHED 2"]))

    def test_a_member_unmapped_before_the_run_is_refreshed_in_the_same_run(self):
        nextcloud, output = self.run_main(
            mapped("alice"),
            [member("alice"), member("dave")],
            directory=mapped("dave"),
        )

        self.assertIn([*PREFIX, "ldap:check-user", "--update", "dave"], nextcloud.calls)
        self.assertEqual((self.code, output[-1]), (0, "REFRESHED 2"))

    def test_without_members_there_is_nothing_to_do(self):
        _, output = self.run_main(mapped("alice"), [])

        self.assertEqual((self.code, output, self.stderr), (0, ["REFRESHED 0"], []))

    def test_an_empty_mapping_is_quiet_while_user_ldap_maps_only_at_login(self):
        nextcloud, output = self.run_main({}, [member("alice")], listing=False)

        self.assertEqual((self.code, output, self.stderr), (0, ["REFRESHED 0"], []))
        self.assertFalse(any("ldap:check-user" in call for call in nextcloud.calls))

    def test_members_no_mapped_account_matches_fail_in_one_line(self):
        nextcloud, output = self.run_main(
            {"uuid-of-another-attribute": "zed"}, [member("alice"), member("bob")]
        )

        self.assertEqual(self.code, 1)
        self.assertEqual(
            self.stderr,
            [
                (
                    "FAILED none of the 2 directory members matches one of the "
                    "1 accounts user_ldap mapped"
                )
            ],
        )
        self.assertEqual(output, [])
        self.assertFalse(any("ldap:check-user" in call for call in nextcloud.calls))

    def test_an_empty_mapping_fails_while_user_ldap_lists_the_directory(self):
        _, output = self.run_main({}, [member("alice")])

        self.assertEqual(self.code, 1)
        self.assertEqual(
            self.stderr,
            [
                (
                    "FAILED user_ldap mapped none of the 1 directory members "
                    "although it lists the directory"
                )
            ],
        )
        self.assertEqual(output, [])

    def test_a_login_a_local_account_holds_is_refreshed_under_its_mapped_name(self):
        nextcloud, output = self.run_main(
            {"uuid-platformadmin": "platformadmin_1859"},
            [member("platformadmin", street="Admin Rd 1")],
        )

        self.assertIn(
            [*PREFIX, "ldap:check-user", "--update", "platformadmin_1859"],
            nextcloud.calls,
        )
        self.assertNotIn(
            [*PREFIX, "ldap:check-user", "--update", "platformadmin"],
            nextcloud.calls,
        )
        self.assertEqual(nextcloud.addresses, {"platformadmin_1859": "Admin Rd 1"})
        self.assertEqual(output, ["CHANGED platformadmin_1859 address", "REFRESHED 1"])

    def test_the_composed_address_is_written_only_where_it_differs(self):
        nextcloud, output = self.run_main(
            mapped("alice", "bob"),
            [
                member(
                    "alice",
                    street="Hauptstraße 1",
                    postalCode="10115",
                    l="Berlin",
                    st="BE",
                    c="DE",
                ),
                member("bob", street="Side Rd 2", c="NL"),
            ],
            {"bob": "Side Rd 2, NL"},
        )

        self.assertEqual(
            nextcloud.addresses["alice"], "Hauptstraße 1, 10115 Berlin, BE, DE"
        )
        self.assertIn(
            [
                *PREFIX,
                "user:profile",
                "alice",
                "address",
                "Hauptstraße 1, 10115 Berlin, BE, DE",
            ],
            nextcloud.calls,
        )
        self.assertNotIn(
            [*PREFIX, "user:profile", "bob", "address", "Side Rd 2, NL"],
            nextcloud.calls,
        )
        self.assertEqual(output, ["CHANGED alice address", "REFRESHED 2"])

    def test_an_address_the_directory_no_longer_holds_is_cleared(self):
        nextcloud, output = self.run_main(
            mapped("alice"), [member("alice")], {"alice": "Old 1"}
        )

        self.assertEqual(nextcloud.addresses["alice"], "")
        self.assertEqual(output, ["CHANGED alice address", "REFRESHED 1"])

    def test_a_member_without_attributes_is_refreshed_and_keeps_its_address(self):
        legacy = {"username": "alice", "email": "", "name": "", "uuid": "uuid-alice"}

        nextcloud, output = self.run_main(
            mapped("alice"), [legacy], {"alice": "Kept 1"}
        )

        self.assertEqual(nextcloud.addresses["alice"], "Kept 1")
        self.assertIn(
            [*PREFIX, "ldap:check-user", "--update", "alice"], nextcloud.calls
        )
        self.assertEqual(output, ["REFRESHED 1"])

    def test_the_mapping_script_reads_the_user_ldap_mapping_table(self):
        self.assertEqual(self.mod.MAPPING_PROGRAM, MAPPING.name)
        self.assertIn('->from("ldap_user_mapping")', self.script)
        self.assertIn(
            'array_column($rows, "owncloud_name", "directory_uuid")',
            self.script,
        )
        self.assertIn("(object)", self.script)

    def test_the_hook_never_dials_the_directory(self):
        source = read_text(str(SCRIPT))

        self.assertNotIn("ldap_client", source)
        self.assertNotIn("RBAC_SYNC_LDAP", source)

    def test_the_hook_declares_the_attributes_it_composes(self):
        include = read_text(str(TASKS))

        self.assertIn(
            'NEXTCLOUD_ADDRESS_ATTRIBUTES: "{{ rbac_sync_attributes | to_json }}"',
            include,
        )
        self.assertIn(
            "- { name: ldap_user_mapping.php, content: \"{{ lookup('file', "
            "role_path ~ '/files/php/utils/ldap_user_mapping.php') }}\" }",
            include,
        )
        self.assertIn(
            "NEXTCLOUD_LDAP_USER_LISTING: \"{{ 'true' if (lookup('config', "
            "application_id, 'addons.user_ldap.config.user_directory.enabled') "
            "| bool) else 'false' }}\"",
            include,
        )

    def test_user_ldap_locks_the_address_through_the_street(self):
        self.assertEqual(
            address_mapping(load_yaml(USER_LDAP_ADDON)),
            "{{ LDAP.USER.ATTRIBUTES.STREET }}",
        )

    def test_the_hook_runs_on_every_timer_run_while_user_ldap_maps_the_address(self):
        include = load_yaml_any(TASKS)[0]["vars"]

        self.assertIs(include["rbac_sync_skip_unchanged"], False)
        self.assertFalse(
            leaves_a_street_only_address(load_yaml(USER_LDAP_ADDON), include)
        )

    def test_the_timer_refreshes_through_a_nextcloud_task_of_any_slot(self):
        include = load_yaml_any(TASKS)[0]["vars"]

        self.assertIs(
            include["rbac_sync_any_slot"],
            True,
            "in swarm the RBAC timer runs only on the OpenLDAP node, which may hold any Nextcloud task slot",
        )

    def test_a_skipping_hook_beside_an_address_mapping_is_reported(self):
        addon = load_yaml(USER_LDAP_ADDON)
        skipping = {"rbac_sync_skip_unchanged": True}
        unmapped = {
            "config": {
                "plugin_configuration": [
                    {
                        "configkey": "{{ NEXTCLOUD_LDAP_CONFIG_PREFIX }}ldap_attr_address",
                        "configvalue": "",
                    }
                ]
            }
        }

        self.assertTrue(leaves_a_street_only_address(addon, skipping))
        self.assertFalse(leaves_a_street_only_address(unmapped, skipping))

    def test_empty_parts_leave_no_separator_behind(self):
        self.assertEqual(
            self.mod.compose_address("", "", "Berlin", "", "DE"), "Berlin, DE"
        )
        self.assertEqual(self.mod.compose_address("", "", "", "", ""), "")

    def test_a_failing_refresh_stops_the_hook(self):
        script = self.script

        def failing(argv, **kwargs):
            if "ldap:check-user" in argv:
                raise subprocess.CalledProcessError(1, argv)
            mapping = json.dumps(mapped("alice"))
            stdout = f"LDAP_MAPPING {mapping}\n" if kwargs["input"] == script else ""
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        with self.assertRaises(subprocess.CalledProcessError):
            self.mod.main(self.environ([member("alice")]), run=failing)


if __name__ == "__main__":
    unittest.main()
