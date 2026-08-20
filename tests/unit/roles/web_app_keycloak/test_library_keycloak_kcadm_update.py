from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from typing import TYPE_CHECKING
from unittest.mock import patch

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-keycloak"
LIB_PATH = PROJECT_ROOT / "library" / "keycloak_kcadm_update.py"
MODUTILS_PATH = PROJECT_ROOT / "utils" / "kcadm_json.py"


def _load_py_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _install_role_local_kcadm_json_into_ansible_module_utils() -> None:
    """
    Make: from ansible.module_utils.kcadm_json import ...
    resolve to utils/kcadm_json.py (the global module_utils dir).
    """
    role_modutils = _load_py_module(
        "role_web_app_keycloak_module_utils_kcadm_json_for_ansible", MODUTILS_PATH
    )

    try:
        importlib.import_module("ansible.module_utils.basic")
    except ImportError:
        if "ansible" not in sys.modules:
            sys.modules["ansible"] = types.ModuleType("ansible")
        if "ansible.module_utils" not in sys.modules:
            sys.modules["ansible.module_utils"] = types.ModuleType(
                "ansible.module_utils"
            )
        basic = types.ModuleType("ansible.module_utils.basic")
        basic.AnsibleModule = object
        sys.modules["ansible.module_utils.basic"] = basic

    sys.modules["ansible.module_utils.kcadm_json"] = role_modutils

    scopes_modutils = _load_py_module(
        "role_web_app_keycloak_module_utils_keycloak_scopes_for_ansible",
        PROJECT_ROOT / "utils" / "keycloak_scopes.py",
    )
    sys.modules["ansible.module_utils.keycloak_scopes"] = scopes_modutils


class DummyModule:
    def fail_json(self, **kwargs):
        raise AssertionError(f"Unexpected fail_json call: {kwargs}")


class DummyCompleted:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout.encode()
        self.stderr = stderr.encode()


class TestKeycloakKcadmUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_role_local_kcadm_json_into_ansible_module_utils()
        cls.mod = _load_py_module(
            "role_web_app_keycloak_library_keycloak_kcadm_update", LIB_PATH
        )

    def test_get_api_and_lookup_field_defaults(self):
        m = self.mod
        self.assertEqual(
            m.get_api_and_lookup_field("client", None), ("clients", "clientId")
        )
        self.assertEqual(
            m.get_api_and_lookup_field("component", None), ("components", "name")
        )
        self.assertEqual(
            m.get_api_and_lookup_field("client-scope", None), ("client-scopes", "name")
        )
        self.assertEqual(m.get_api_and_lookup_field("realm", None), ("realms", "id"))

    def test_deep_merge_recursive(self):
        m = self.mod
        a = {"a": 1, "x": {"y": 1, "z": 2}}
        b = {"b": 2, "x": {"y": 99}}
        got = m.deep_merge(a, b)
        self.assertEqual(got["a"], 1)
        self.assertEqual(got["b"], 2)
        self.assertEqual(got["x"]["y"], 99)
        self.assertEqual(got["x"]["z"], 2)

    def test_resolve_object_id_client_scope(self):
        m = self.mod
        dummy = DummyModule()

        scopes_json = '[0.001s][warning][os] noise before json\n[{"id":"s1","name":"a"},{"id":"s2","name":"rbac"}]'

        with patch.object(m, "run_kcadm", return_value=(0, scopes_json, "")):
            obj_id, exists = m.resolve_object_id(
                dummy,
                object_kind="client-scope",
                api="client-scopes",
                lookup_field="name",
                lookup_value="rbac",
                realm="example",
                kcadm_exec="kcadm",
            )
        self.assertTrue(exists)
        self.assertEqual(obj_id, "s2")

    def test_resolve_object_id_client(self):
        m = self.mod
        dummy = DummyModule()

        clients_json = '[0.001s][warning] noise\n[{"id":"c1","clientId":"foo"},{"id":"c2","clientId":"bar"}]'

        with patch.object(m, "run_kcadm", return_value=(0, clients_json, "")):
            obj_id, exists = m.resolve_object_id(
                dummy,
                object_kind="client",
                api="clients",
                lookup_field="clientId",
                lookup_value="bar",
                realm="example",
                kcadm_exec="kcadm",
            )
        self.assertTrue(exists)
        self.assertEqual(obj_id, "c2")

    def test_resolve_object_id_component(self):
        m = self.mod
        dummy = DummyModule()

        comps_json = '[0.001s][warning] noise\n[{"id":"x1","name":"ldap"},{"id":"x2","name":"oidc"}]'

        with patch.object(m, "run_kcadm", return_value=(0, comps_json, "")):
            obj_id, exists = m.resolve_object_id(
                dummy,
                object_kind="component",
                api="components",
                lookup_field="name",
                lookup_value="oidc",
                realm="example",
                kcadm_exec="kcadm",
            )
        self.assertTrue(exists)
        self.assertEqual(obj_id, "x2")

    def test_run_kcadm_retries_dead_cid_with_fresh_resolved_id(self):
        m = self.mod
        module = DummyModule()
        module._kcadm_cid_state = {
            "cid_resolve_cmd": "resolve-cid",
            "current_cid": "deadbeef0000",
        }

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd == "resolve-cid":
                return DummyCompleted(0, "live1234abcd\n", "")
            if "deadbeef0000" in cmd:
                return DummyCompleted(
                    1, "", "Error response from daemon: No such container: deadbeef0000"
                )
            return DummyCompleted(0, "[]", "")

        with (
            patch.object(m.subprocess, "run", side_effect=fake_run),
            patch.object(m.time, "sleep", return_value=None),
        ):
            rc, out, _ = m.run_kcadm(
                module,
                "container exec -i deadbeef0000 kcadm get clients",
                ignore_rc=True,
            )

        self.assertEqual(rc, 0)
        self.assertEqual(out, "[]")
        self.assertEqual(module._kcadm_cid_state["current_cid"], "live1234abcd")
        self.assertTrue(any("live1234abcd" in c for c in calls))

    def test_run_kcadm_no_resolver_does_not_retry(self):
        m = self.mod
        module = DummyModule()

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return DummyCompleted(
                1, "", "Error response from daemon: No such container: deadbeef0000"
            )

        with patch.object(m.subprocess, "run", side_effect=fake_run):
            rc, _out, _err = m.run_kcadm(
                module,
                "container exec -i deadbeef0000 kcadm get clients",
                ignore_rc=True,
            )

        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1)

    def test_get_current_object_parses_noisy(self):
        m = self.mod
        dummy = DummyModule()

        noisy_obj = '[0.001s][warning] noise\n{"id":"abc","name":"thing"}'
        with patch.object(m, "run_kcadm", return_value=(0, noisy_obj, "")):
            cur = m.get_current_object(
                dummy,
                object_kind="client",
                api="clients",
                object_id="abc",
                realm="example",
                kcadm_exec="kcadm",
            )
        self.assertEqual(cur, {"id": "abc", "name": "thing"})

    def _run_converge(self, desired, assignments, catalog):
        """Drive converge_client_scope_lists with a fake kcadm; returns the
        mutating commands it issued, in order."""
        m = self.mod
        dummy = DummyModule()
        mutations = []

        def fake_run_kcadm(_module, cmd, ignore_rc=False):
            for kind, payload in assignments.items():
                if f"get clients/c1/{kind} " in cmd:
                    return 0, payload, ""
            if "get client-scopes " in cmd:
                return 0, catalog, ""
            mutations.append(cmd)
            return 0, "", ""

        changed = m.converge_client_scope_lists(
            fake_run_kcadm, dummy, "c1", desired, "example", "kcadm"
        )
        return changed, mutations

    def test_converge_client_scopes_adds_and_removes(self):
        changed, mutations = self._run_converge(
            desired={"defaultClientScopes": ["a", "b"]},
            assignments={
                "default-client-scopes": '[{"id":"s-old","name":"old"},{"id":"s-a","name":"a"}]'
            },
            catalog='[{"id":"s-b","name":"b"},{"id":"s-old","name":"old"}]',
        )
        self.assertTrue(changed)
        self.assertEqual(
            mutations,
            [
                "kcadm delete clients/c1/default-client-scopes/s-old -r example",
                "kcadm update clients/c1/default-client-scopes/s-b -r example",
            ],
        )

    def test_converge_client_scopes_noop_when_in_sync(self):
        changed, mutations = self._run_converge(
            desired={"defaultClientScopes": ["a"]},
            assignments={"default-client-scopes": '[{"id":"s-a","name":"a"}]'},
            catalog='[{"id":"s-a","name":"a"}]',
        )
        self.assertFalse(changed)
        self.assertEqual(mutations, [])

    def test_converge_client_scopes_removals_precede_additions_across_lists(self):
        # "x" moves default -> optional: it must be unassigned from default
        # BEFORE it is assigned to optional.
        changed, mutations = self._run_converge(
            desired={"defaultClientScopes": [], "optionalClientScopes": ["x"]},
            assignments={
                "default-client-scopes": '[{"id":"s-x","name":"x"}]',
                "optional-client-scopes": "[]",
            },
            catalog='[{"id":"s-x","name":"x"}]',
        )
        self.assertTrue(changed)
        self.assertEqual(
            mutations,
            [
                "kcadm delete clients/c1/default-client-scopes/s-x -r example",
                "kcadm update clients/c1/optional-client-scopes/s-x -r example",
            ],
        )

    def test_converge_client_scopes_skips_undeclared_lists(self):
        changed, mutations = self._run_converge(
            desired={"clientId": "no-scope-lists-here"},
            assignments={"default-client-scopes": '[{"id":"s-a","name":"a"}]'},
            catalog="[]",
        )
        self.assertFalse(changed)
        self.assertEqual(mutations, [])


if __name__ == "__main__":
    unittest.main()
