"""Unit tests for ``plugins/lookup/objstore_consumers.py``.

Pins the consumer predicate: a role is a consumer when its binding names the
engine and is shared, whatever the role is called, and the provider is never a
consumer of its own store.
"""

import importlib.util
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _binding(engine="seaweedfs", shared=True):
    return {"engine": engine, "shared": shared}


class ObjstoreConsumersLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            "plugins/lookup/objstore_consumers.py", "lookup_objstore_consumers"
        )

    def setUp(self):
        self._original_loader = self.mod.lookup_loader
        self._bindings: dict = {}
        self._applications: dict = {}
        self.objstore_calls: list[str] = []

        def _get(name, **_kwargs):
            if name == "applications":
                return mock.MagicMock(run=lambda *_a, **_k: [self._applications])
            return mock.MagicMock(run=self._objstore_run)

        loader_mock = mock.MagicMock()
        loader_mock.get.side_effect = _get
        self.mod.lookup_loader = loader_mock

    def tearDown(self):
        self.mod.lookup_loader = self._original_loader

    def _objstore_run(self, terms, **_kwargs):
        role = str(terms[0])
        self.objstore_calls.append(role)
        return [self._bindings.get(role)]

    def _run(self, group_names, bindings, applications=None, terms=("seaweedfs",)):
        self._bindings = bindings
        engine = str(terms[0]) if terms else "seaweedfs"
        if applications is None:
            applications = {role: {"services": {engine: {}}} for role in bindings}
        self._applications = applications
        lk = self.mod.LookupModule()
        lk._loader = mock.MagicMock()
        lk._templar = mock.MagicMock()
        return lk.run(list(terms), variables={"group_names": list(group_names)})

    def test_missing_term_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([], {}, terms=())

    def test_unknown_engine_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([], {}, terms=("ceph",))

    def test_no_groups_returns_empty_list(self):
        self.assertEqual(self._run([], {}), [[]])

    def test_multi_domain_consumer_is_counted(self):
        result = self._run(
            ["web-app-matrix", "web-app-seaweedfs"],
            {"web-app-matrix": _binding()},
        )
        self.assertEqual(result, [["web-app-matrix"]])

    def test_provider_is_not_its_own_consumer(self):
        result = self._run(
            ["web-app-seaweedfs"],
            {"web-app-seaweedfs": _binding()},
        )
        self.assertEqual(result, [[]])

    def test_other_engine_is_excluded(self):
        result = self._run(
            ["web-app-a"],
            {"web-app-a": _binding(engine="minio")},
        )
        self.assertEqual(result, [[]])

    def test_unshared_consumer_is_excluded(self):
        result = self._run(
            ["web-app-a"],
            {"web-app-a": _binding(shared=False)},
        )
        self.assertEqual(result, [[]])

    def test_consumer_is_selected_by_binding_not_by_role_name(self):
        result = self._run(
            ["svc-db-postgres", "web-app-a"],
            {"svc-db-postgres": _binding(), "web-app-a": _binding()},
        )
        self.assertEqual(result, [["svc-db-postgres", "web-app-a"]])

    def test_role_without_a_services_block_is_never_looked_up(self):
        result = self._run(
            ["web-app-a", "web-app-b"],
            {"web-app-a": _binding(), "web-app-b": _binding()},
            applications={"web-app-b": {"services": {"seaweedfs": {}}}},
        )
        self.assertEqual(result, [["web-app-b"]])
        self.assertEqual(self.objstore_calls, ["web-app-b"])

    def test_unbound_role_payload_is_skipped(self):
        result = self._run(
            ["svc-swarm-manager", "web-app-a"],
            {
                "svc-swarm-manager": {"engine": "", "shared": False},
                "web-app-a": _binding(),
            },
        )
        self.assertEqual(result, [["web-app-a"]])

    def test_group_without_binding_is_skipped(self):
        result = self._run(
            ["svc-swarm-manager", "web-app-a", "web-app-b"],
            {"web-app-b": _binding()},
        )
        self.assertEqual(result, [["web-app-b"]])

    def test_result_is_sorted_and_deduplicated(self):
        result = self._run(
            ["web-app-zeta", "web-app-alpha", "web-app-zeta"],
            {"web-app-zeta": _binding(), "web-app-alpha": _binding()},
        )
        self.assertEqual(result, [["web-app-alpha", "web-app-zeta"]])


if __name__ == "__main__":
    unittest.main()
