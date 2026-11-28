from __future__ import annotations

import importlib.util
import json
import re
import unittest

from ansible.errors import AnsibleFilterError

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from ._render import PROXMOX, ROLE
from .files._fake_pve import PERL, run_script

_SPEC = importlib.util.spec_from_file_location(
    "proxmox_workspace_filters", ROLE / "filter_plugins" / "proxmox_workspace.py"
)
_FILTERS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FILTERS)
proxmox_workspace_acls = _FILTERS.proxmox_workspace_acls

VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
ROLES = VARS["PROXMOX_WORKSPACE_ROLES"]
README = read_text(str(ROLE / "README.md"))
SCRIPT = read_text(str(ROLE / "files" / "perl" / "workspace.pl"))
TASKS = load_yaml_any(str(ROLE / "tasks" / "workspace.yml"), default_if_missing=[])
WORKSPACE = "0c6f7a52-3d1e-4b8a-9f00-2a7b1c9d4e5f"
POOL = f"ws-{WORKSPACE}"
USER = f"{POOL}@pve"
TOKEN = f"{USER}!provision"
SECRET = "5ee1e4b2-token-secret"
WORKSPACE_PRIVILEGES = frozenset(
    {
        "Pool.Audit",
        "VM.Allocate",
        "VM.Audit",
        "VM.Config.CDROM",
        "VM.Config.CPU",
        "VM.Config.Cloudinit",
        "VM.Config.Disk",
        "VM.Config.HWType",
        "VM.Config.Memory",
        "VM.Config.Network",
        "VM.Config.Options",
        "VM.GuestAgent.Audit",
        "VM.PowerMgmt",
    }
)
FORBIDDEN_PREFIXES = ("Sys.", "Permissions.", "Realm.", "User.", "Group.", "Mapping.")


def _readme_privileges(role: str) -> set[str]:
    match = re.search(rf"^- `{role}`[^:]*: (.+)$", README, re.MULTILINE)
    return (
        set(re.findall(r"`([A-Za-z]+\.[A-Za-z.]+)`", match.group(1)))
        if match
        else set()
    )


def role_findings(roles: dict) -> list[str]:
    """Args:
        roles: role name to privilege list, as ``PROXMOX_WORKSPACE_ROLES``.

    Returns:
        Every privilege that differs from the README or reaches outside the workspace.
    """
    findings = []
    for role, privileges in roles.items():
        if set(privileges) != _readme_privileges(role):
            findings.append(
                f"{role} holds {sorted(privileges)}, the README lists {sorted(_readme_privileges(role))}"
            )
        findings.extend(
            f"{role} holds {privilege}"
            for privilege in privileges
            if privilege.startswith(FORBIDDEN_PREFIXES)
        )
    return findings


def acl_findings(acls: list[dict], roles: dict) -> list[str]:
    """Args:
        acls: the ACLs apply writes for one workspace.
        roles: role name to privilege list.

    Returns:
        Every ACL outside the pool, its storage and bridge and the two templates,
        and every clone right beyond ``VM.Clone``.
    """
    templates = PROXMOX["workspaces"]["templates"]
    outside = [acl for acl in acls if not acl["path"].startswith(f"/pool/{POOL}")]
    clone = [acl for acl in outside if acl["path"].startswith("/vms/")]
    findings = []
    if sorted(acl["path"] for acl in clone) != sorted(
        f"/vms/{templates[k]}" for k in ("kvm", "emulated")
    ):
        findings.append(f"clone ACLs on {[acl['path'] for acl in clone]}")
    if {acl["role"] for acl in clone} != {"InfinitoTemplateClone"}:
        findings.append(f"clone roles {[acl['role'] for acl in clone]}")
    if roles["InfinitoTemplateClone"] != ["VM.Clone"]:
        findings.append(f"InfinitoTemplateClone holds {roles['InfinitoTemplateClone']}")
    for acl in outside:
        if acl["path"].startswith("/vms/"):
            continue
        if (
            acl["path"] == f"/storage/{PROXMOX['workspaces']['storage']}"
            and acl["role"] == "InfinitoWorkspaceStorage"
        ):
            continue
        if (
            acl["path"] == f"/sdn/zones/localnetwork/{PROXMOX['workspaces']['bridge']}"
            and acl["role"] == "InfinitoWorkspaceBridge"
        ):
            continue
        findings.append(f"{acl['role']} on {acl['path']}")
    if any(acl["propagate"] for acl in outside):
        findings.append("an ACL outside the pool propagates")
    return findings


def _env(action: str = "apply", stored: str = "1") -> dict[str, str]:
    return {
        "PROXMOX_WORKSPACE_ACTION": action,
        "PROXMOX_WORKSPACE_ID": WORKSPACE,
        "PROXMOX_WORKSPACE_TOKEN_NAME": VARS["PROXMOX_WORKSPACE_TOKEN_NAME"],
        "PROXMOX_WORKSPACE_ROLES": json.dumps(ROLES),
        "PROXMOX_WORKSPACE_ACLS": json.dumps(
            proxmox_workspace_acls(WORKSPACE, PROXMOX["workspaces"])
        ),
        "PROXMOX_WORKSPACE_ISSUED": stored,
    }


def _acl_tree(entries: list[tuple[str, str, str, str]]) -> dict:
    root: dict = {}
    for path, kind, who, role in entries:
        node = root
        for part in [p for p in path.split("/") if p]:
            node = node.setdefault("children", {}).setdefault(part, {})
        node.setdefault(kind, {}).setdefault(who, {})[role] = 1
    return root


def _converged(vms: dict | None = None) -> dict:
    entries = [
        (acl["path"], kind, who, acl["role"])
        for acl in proxmox_workspace_acls(WORKSPACE, PROXMOX["workspaces"])
        for kind, who in (("users", USER), ("tokens", TOKEN))
    ]
    return {
        "user.cfg": {
            "roles": {
                role: dict.fromkeys(privileges, 1) for role, privileges in ROLES.items()
            },
            "pools": {POOL: {"vms": vms or {}}},
            "users": {USER: {"enable": 1, "tokens": {"provision": {"privsep": 1}}}},
            "acl_root": _acl_tree(entries),
        }
    }


def _empty() -> dict:
    return {"user.cfg": {"roles": {}, "pools": {}, "users": {}, "acl_root": {}}}


def _result(run) -> dict:
    return json.loads(run.stdout.strip().splitlines()[-1])


def _methods(run) -> list[str]:
    return [call["method"].split("::")[-1] for call in run.calls]


class TestWorkspaceRoles(unittest.TestCase):
    def test_the_workspace_role_holds_exactly_its_privileges(self):
        self.assertEqual(set(ROLES["InfinitoWorkspace"]), WORKSPACE_PRIVILEGES)
        self.assertEqual(role_findings(ROLES), [])
        self.assertEqual(
            ROLES["InfinitoWorkspaceStorage"],
            ["Datastore.AllocateSpace", "Datastore.Audit"],
        )
        self.assertEqual(ROLES["InfinitoWorkspaceBridge"], ["SDN.Use"])

    def test_negative_control_an_added_sys_modify_fails(self):
        planted = {
            **ROLES,
            "InfinitoWorkspace": [*ROLES["InfinitoWorkspace"], "Sys.Modify"],
        }
        self.assertTrue(
            any("Sys.Modify" in finding for finding in role_findings(planted))
        )

    def test_the_workspace_may_only_clone_the_templates(self):
        acls = proxmox_workspace_acls(WORKSPACE, PROXMOX["workspaces"])
        self.assertEqual(acl_findings(acls, ROLES), [])
        self.assertEqual(ROLES["InfinitoTemplateClone"], ["VM.Clone"])
        self.assertEqual(
            [acl["path"] for acl in acls if acl["role"] == "InfinitoTemplateClone"],
            ["/vms/9000", "/vms/9001"],
        )
        self.assertEqual(
            {acl["role"] for acl in acls} - set(ROLES),
            set(),
            "every granted role is converged",
        )

    def test_negative_control_an_added_disk_right_on_the_templates_fails(self):
        planted = {**ROLES, "InfinitoTemplateClone": ["VM.Clone", "VM.Config.Disk"]}
        acls = proxmox_workspace_acls(WORKSPACE, PROXMOX["workspaces"])
        self.assertNotEqual(acl_findings(acls, planted), [])
        extra = [
            *acls,
            {"path": "/vms/100", "role": "InfinitoTemplateClone", "propagate": 0},
        ]
        self.assertNotEqual(acl_findings(extra, ROLES), [])

    def test_a_malformed_workspace_id_is_refused(self):
        for bad in (
            "ws-1",
            "0C6F7A52-3D1E-4B8A-9F00-2A7B1C9D4E5F",
            f"{WORKSPACE}/../x",
        ):
            with self.assertRaises(AnsibleFilterError, msg=bad):
                proxmox_workspace_acls(bad, PROXMOX["workspaces"])


@unittest.skipUnless(PERL, "perl is not installed")
class TestWorkspaceScript(unittest.TestCase):
    def _apply(self, state: dict, stored: str = "1"):
        return run_script(
            SCRIPT,
            state,
            _env("apply", stored),
            {
                "PVE::API2::User->generate_token": {
                    "value": SECRET,
                    "full-tokenid": TOKEN,
                }
            },
        )

    def test_apply_creates_pool_user_token_and_acls(self):
        run = self._apply(_empty(), stored="0")
        self.assertEqual(run.returncode, 0, run.stderr)
        methods = _methods(run)
        self.assertEqual(methods.count("Role->create_role"), len(ROLES))
        self.assertIn("Pool->create_pool", methods)
        self.assertIn("User->create_user", methods)
        token = next(
            call for call in run.calls if call["method"].endswith("generate_token")
        )
        self.assertEqual(token["param"]["privsep"], 1)
        self.assertEqual(token["param"]["userid"], USER)
        grants = [
            call["param"] for call in run.calls if call["method"].endswith("update_acl")
        ]
        acls = proxmox_workspace_acls(WORKSPACE, PROXMOX["workspaces"])
        self.assertEqual(len(grants), 2 * len(acls))
        self.assertEqual(
            {g.get("users") or g.get("tokens") for g in grants}, {USER, TOKEN}
        )
        self.assertEqual(
            _result(run), {"workspace": WORKSPACE, "token": TOKEN, "secret": SECRET}
        )
        self.assertNotIn(SECRET, "\n".join(run.stdout.splitlines()[:-1]) + run.stderr)

    def test_a_second_apply_changes_nothing_and_keeps_the_token(self):
        run = self._apply(_converged())
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.calls, [])
        self.assertNotIn("[CHANGED]", run.stdout)
        self.assertIsNone(_result(run)["secret"])

    def test_a_token_whose_secret_openbao_lost_is_issued_anew(self):
        run = self._apply(_converged(), stored="0")
        self.assertEqual(_methods(run), ["User->remove_token", "User->generate_token"])
        self.assertEqual(_result(run)["secret"], SECRET)

    def test_a_stray_acl_is_revoked(self):
        state = _converged()
        state["user.cfg"]["acl_root"]["children"]["vms"]["children"]["100"] = {
            "tokens": {TOKEN: {"InfinitoWorkspace": 1}}
        }
        run = self._apply(state)
        self.assertEqual(
            [call["param"] for call in run.calls],
            [
                {
                    "path": "/vms/100",
                    "roles": "InfinitoWorkspace",
                    "tokens": TOKEN,
                    "delete": 1,
                }
            ],
        )

    def test_a_drifted_role_is_reset(self):
        state = _converged()
        state["user.cfg"]["roles"]["InfinitoTemplateClone"]["VM.Config.Disk"] = 1
        run = self._apply(state)
        self.assertEqual(
            run.calls,
            [
                {
                    "method": "PVE::API2::Role->update_role",
                    "param": {"roleid": "InfinitoTemplateClone", "privs": "VM.Clone"},
                }
            ],
        )

    def test_destroy_refuses_while_the_pool_holds_a_vm(self):
        run = run_script(SCRIPT, _converged({"101": 1}), _env("destroy"))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("101", run.stderr)
        self.assertEqual(run.calls, [])

    def test_destroy_removes_acls_token_user_and_pool(self):
        run = run_script(SCRIPT, _converged(), _env("destroy"))
        self.assertEqual(run.returncode, 0, run.stderr)
        methods = _methods(run)
        self.assertEqual(
            methods[-3:],
            ["User->remove_token", "User->delete_user", "Pool->delete_pool"],
        )
        revokes = [
            call["param"] for call in run.calls if call["method"].endswith("update_acl")
        ]
        self.assertTrue(all(param["delete"] == 1 for param in revokes))
        self.assertEqual(
            len(revokes),
            2 * len(proxmox_workspace_acls(WORKSPACE, PROXMOX["workspaces"])),
        )

    def test_destroy_of_a_gone_workspace_changes_nothing(self):
        run = run_script(SCRIPT, _empty(), _env("destroy"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.calls, [])

    def test_a_malformed_call_is_refused(self):
        for env in (
            {**_env(), "PROXMOX_WORKSPACE_ID": "ws-1"},
            {**_env(), "PROXMOX_WORKSPACE_ACTION": "rename"},
        ):
            run = run_script(SCRIPT, _empty(), env)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("[FAIL]", run.stderr)
            self.assertEqual(run.calls, [])


class TestWorkspaceTasks(unittest.TestCase):
    def test_the_secret_goes_to_its_tenant_path_only(self):
        store = next(t for t in TASKS if "Keep the token" in t.get("name", ""))
        self.assertEqual(
            store["vars"]["openbao_kv_mount"], "{{ PROXMOX_TENANT_MOUNT }}"
        )
        self.assertEqual(
            store["vars"]["openbao_kv_path"], "ws-{{ WORKSPACE }}-provision/proxmox"
        )
        self.assertEqual(VARS["PROXMOX_TENANT_MOUNT"], "tenant")
        call = next(t for t in TASKS if "ansible.builtin.shell" in t)
        self.assertEqual(call["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")
        self.assertEqual(
            call["ansible.builtin.shell"]["stdin"],
            "{{ lookup('file', 'perl/workspace.pl') }}",
        )
        self.assertEqual(
            sorted(call["environment"]),
            sorted(
                re.findall(
                    r"-e (PROXMOX_WORKSPACE_\w+)", call["ansible.builtin.shell"]["cmd"]
                )
            ),
        )
        issued = call["environment"]["PROXMOX_WORKSPACE_ISSUED"]
        self.assertIn("get('token_id', '') | length > 0 else '0'", issued)


if __name__ == "__main__":
    unittest.main()
