import base64
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

BOOTSTRAP = PROJECT_ROOT / "roles/web-app-fusiondirectory/files/shell/ldap/bootstrap.sh"
BASE = "dc=example,dc=test"
ACLROLES = f"ou=aclroles,{BASE}"
ADMIN_ROLE = f"cn=admin,{ACLROLES}"
USER_MANAGER_ROLE = f"cn=user-manager,{ACLROLES}"
SELF_SERVICE_ROLE = f"cn=self-service,{ACLROLES}"
OLD_ADMIN = f"uid=platform_administrator,ou=users,{BASE}"
NEW_ADMIN = f"uid=platformadmin,ou=users,{BASE}"
BIBER = f"uid=biber,ou=users,{BASE}"
GONE = f"uid=gone,ou=users,{BASE}"
ADMIN_GROUP = f"cn=web-app-fusiondirectory-administrator,ou=roles,{BASE}"
USER_MANAGER_GROUP = f"cn=web-app-fusiondirectory-user-manager,ou=roles,{BASE}"
SELF_SERVICE_GROUP = f"cn=web-app-fusiondirectory-self-service,ou=roles,{BASE}"
CONFIG = f"cn=config,ou=fusiondirectory,{BASE}"
EXISTING = [
    ACLROLES,
    ADMIN_ROLE,
    USER_MANAGER_ROLE,
    SELF_SERVICE_ROLE,
    f"ou=fusiondirectory,{BASE}",
    CONFIG,
    f"ou=locks,ou=fusiondirectory,{BASE}",
    f"ou=snapshots,{BASE}",
    NEW_ADMIN,
    BIBER,
    ADMIN_GROUP,
    USER_MANAGER_GROUP,
    SELF_SERVICE_GROUP,
]

STUB = """#!/usr/bin/env python3
import os
import sys

tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
acl_file = os.environ["STUB_ACL_FILE"]
with open(acl_file, encoding="utf-8") as held:
    acl = held.read().splitlines()
if tool != "ldapsearch":
    ldif = sys.stdin.read()
    with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
        log.write(f"--- {tool}\\n{ldif}")
    operation = None
    for line in ldif.splitlines():
        if line in ("delete: gosaAclEntry", "add: gosaAclEntry"):
            operation = line.split(":")[0]
        elif line == "-":
            operation = None
        elif operation and line.startswith("gosaAclEntry: "):
            value = line.removeprefix("gosaAclEntry: ")
            if operation == "delete":
                acl.remove(value)
            else:
                acl.append(value)
    with open(acl_file, "w", encoding="utf-8") as held:
        held.write("\\n".join(acl))
    sys.exit(0)
base = args[args.index("-b") + 1]
if base in os.environ["STUB_FAIL"].splitlines():
    sys.exit(1)
if base == "cn=schema,cn=config":
    for index, name in enumerate(("core-fd", "core-fd-conf", "ldapns", "template-fd")):
        print(f"dn: cn={{{index}}}{name},cn=schema,cn=config")
    sys.exit(0)
if "gosaAclEntry" in args:
    print(f"dn: {base}\\nobjectClass: gosaAcl")
    for value in acl:
        print(f"gosaAclEntry: {value}")
    sys.exit(0)
if base not in os.environ["STUB_EXISTING"].splitlines():
    sys.exit(32)
print(f"dn: {base}")
print(f"fdLoginMethod: {os.environ['FD_LOGIN_METHOD']}")
print(f"fdHttpHeaderAuthHeaderName: {os.environ['FD_HTTP_HEADER_NAME']}")
"""


def _b64(value):
    return base64.b64encode(value.encode()).decode()


def _acl(priority, role, *members):
    return f"{priority}:subtree:{_b64(role)}:{','.join(_b64(m) for m in members)}"


CLEAN_ACL = [
    _acl(1, ADMIN_ROLE, ADMIN_GROUP),
    _acl(2, USER_MANAGER_ROLE, USER_MANAGER_GROUP),
    _acl(3, SELF_SERVICE_ROLE, SELF_SERVICE_GROUP),
    _acl(4, ADMIN_ROLE, NEW_ADMIN),
]


class TestBootstrap(unittest.TestCase):
    def _run(self, acl, fail):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            for tool in ("ldapsearch", "ldapmodify", "ldapadd"):
                stub = bin_dir / tool
                stub.write_text(STUB, encoding="utf-8")
                stub.chmod(0o755)
            log = root / "modify.log"
            log.write_text("", encoding="utf-8")
            held = root / "acl"
            held.write_text("\n".join(acl), encoding="utf-8")
            env = {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_LOG": str(log),
                "STUB_ACL_FILE": str(held),
                "STUB_EXISTING": "\n".join(EXISTING),
                "STUB_FAIL": "\n".join(fail),
                "LDAP01_HOST": "ldap",
                "LDAP01_PORT": "389",
                "LDAP01_BASE_DN": BASE,
                "LDAP01_ADMIN_DN": f"cn=administrator,{BASE}",
                "LDAP01_ADMIN_PASS": "bind-value-0",
                "FD_ADMIN_DN": NEW_ADMIN,
                "FD_ADMINISTRATOR_GROUP_DN": ADMIN_GROUP,
                "FD_USER_MANAGER_GROUP_DN": USER_MANAGER_GROUP,
                "FD_SELF_SERVICE_GROUP_DN": SELF_SERVICE_GROUP,
                "FD_GROUP_RDN": "ou=groups",
                "FD_HTTP_HEADER_NAME": "X_FORWARDED_PREFERRED_USERNAME",
                "FD_LOGIN_ATTRIBUTE": "uid",
                "FD_LOGIN_METHOD": "LoginHTTPHeader",
                "FD_OGROUP_RDN": "ou=groups",
                "FD_THEME": "breezy",
                "FD_TIMEZONE": "Europe/Berlin",
                "FD_USER_RDN": "ou=users",
            }
            result = subprocess.run(
                ["bash", str(BOOTSTRAP)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.acl = held.read_text(
                encoding="utf-8"
            ).splitlines()  # nocheck: cache-read tempdir
            return result, log.read_text(
                encoding="utf-8"
            )  # nocheck: cache-read tempdir

    def test_an_acl_entry_whose_only_member_is_gone_is_deleted(self):
        stale = _acl(0, ADMIN_ROLE, OLD_ADMIN)
        result, log = self._run([stale, *CLEAN_ACL], [])
        self.assertEqual(sorted(CLEAN_ACL), sorted(self.acl))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(f"delete: gosaAclEntry\ngosaAclEntry: {stale}\n", log)
        self.assertNotIn(f"gosaAclEntry: {stale}\n-\nadd:", log)
        self.assertIn(f"revoked ACL entry 0 from {OLD_ADMIN}", result.stdout)

    def test_an_acl_entry_keeps_its_members_that_still_exist(self):
        mixed = _acl(5, USER_MANAGER_ROLE, GONE, BIBER)
        result, log = self._run([*CLEAN_ACL, mixed], [])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            f"delete: gosaAclEntry\ngosaAclEntry: {mixed}\n-\n"
            f"add: gosaAclEntry\ngosaAclEntry: {_acl(5, USER_MANAGER_ROLE, BIBER)}\n",
            log,
        )

    def test_entries_whose_members_all_exist_stay_untouched(self):
        result, log = self._run(CLEAN_ACL, [])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("delete:", log)
        self.assertNotIn("revoked", result.stdout)
        self.assertNotIn("granted", result.stdout)

    def test_a_grant_after_a_revoke_takes_the_priority_after_the_highest_left(self):
        result, log = self._run([_acl(7, ADMIN_ROLE, OLD_ADMIN), *CLEAN_ACL[:3]], [])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(f"gosaAclEntry: {_acl(4, ADMIN_ROLE, NEW_ADMIN)}\n", log)
        self.assertEqual(sorted(CLEAN_ACL), sorted(self.acl))
        priorities = [value.split(":", 1)[0] for value in self.acl]
        self.assertEqual(len(priorities), len(set(priorities)))

    def test_a_member_lookup_that_errors_fails_instead_of_revoking(self):
        stale = _acl(0, ADMIN_ROLE, OLD_ADMIN)
        result, log = self._run([stale, *CLEAN_ACL], [OLD_ADMIN])
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("delete:", log)


if __name__ == "__main__":
    unittest.main()
