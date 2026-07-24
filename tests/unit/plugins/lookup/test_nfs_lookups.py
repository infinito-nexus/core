import importlib.util
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.storage.nfs import client_src, state_path


def _run(name, variables):
    """Lookups must read resolved values from `variables`; templar.template('{{..}}')
    no-ops on untrusted strings in ansible 2.19+ and emits literal Jinja into exports."""
    spec = importlib.util.spec_from_file_location(name, f"plugins/lookup/{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    lm = m.LookupModule()
    lm._templar = Templar(loader=DataLoader(), variables=variables)
    return lm.run([], variables=variables)[0]


BASE = {
    "storage": {"nfs": {"server": "192.168.244.2"}},
    "RUNTIME": "github",
}


class TestNfsLookups(unittest.TestCase):
    def test_state_path_renders(self):
        self.assertEqual(_run("nfs_state_path", BASE), "/srv/nfs/infinito-state")

    def test_fstype_renders(self):
        self.assertEqual(_run("nfs_fstype", BASE), "nfs4")

    def test_mount_opts_github_soft(self):
        self.assertEqual(
            _run("nfs_mount_opts", BASE),
            "vers=4,rw,soft,timeo=50,retrans=3,local_lock=flock",
        )

    def test_mount_opts_host_hard(self):
        self.assertEqual(
            _run("nfs_mount_opts", {**BASE, "RUNTIME": "host"}),
            "vers=4,rw,hard,timeo=600,local_lock=flock",
        )

    def test_mount_opts_act_soft(self):
        self.assertEqual(
            _run("nfs_mount_opts", {**BASE, "RUNTIME": "act"}),
            "vers=4,rw,soft,timeo=50,retrans=3,local_lock=flock",
        )


def _load(name, variables):
    spec = importlib.util.spec_from_file_location(name, f"plugins/lookup/{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    lm = m.LookupModule()
    lm._templar = Templar(loader=DataLoader(), variables=variables)
    lm._loader = DataLoader()
    return m, lm


class TestNfsConfigBackedLookups(unittest.TestCase):
    """nfs_flavor / nfs_client_src reach the merged-config SPOT through
    lookup('config') via lookup_loader, NOT a utils.cache import."""

    def test_flavor_returns_config_lookup_result(self):
        m, lm = _load("nfs_flavor", {})
        with mock.patch.object(m, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(run=lambda *a, **k: ["ganesha"])
            self.assertEqual(lm.run([], variables={}), ["ganesha"])

    def test_flavor_config_call_shape(self):
        m, lm = _load("nfs_flavor", {})
        calls = []

        def _run(args, **kwargs):
            calls.append((tuple(args), kwargs))
            return ["kernel"]

        with mock.patch.object(m, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(run=_run)
            lm.run([], variables={"RUNTIME": "github"})
        (args, kwargs) = calls[0]
        self.assertEqual(
            args,
            ("svc-storage-nfs-server", "services.nfs-server.flavor", "kernel"),
        )
        self.assertEqual(kwargs.get("variables"), {"RUNTIME": "github"})

    def test_client_src_kernel_v4_uses_root_mount(self):
        nfs = {"server": "10.0.0.2"}
        vars_ = {"storage": {"nfs": nfs}}
        m, lm = _load("nfs_client_src", vars_)
        with mock.patch.object(m, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(run=lambda *a, **k: ["kernel"])
            result = lm.run([], variables=vars_)
        expected = client_src(
            "10.0.0.2",
            4,
            "kernel",
            state_path("/srv/nfs", "infinito-state"),
        )
        self.assertEqual(result, [expected])


if __name__ == "__main__":
    unittest.main()
