import importlib.util
import unittest

from utils import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "sys-svc-wazuh-agent"
_spec = importlib.util.spec_from_file_location(
    "network_filesystems", ROLE / "filter_plugins" / "network_filesystems.py"
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


def result(path, fstype):
    return {"item": path, "stdout": f"{fstype}\n"}


class TestNetworkFilesystems(unittest.TestCase):
    def test_local_filesystems_pass(self):
        results = [
            result(f"/opt/{fstype}", fstype)
            for fstype in ("ext4", "xfs", "btrfs", "overlay", "tmpfs", "fuse.lxcfs")
        ]
        self.assertEqual(module.network_filesystems(results), [])

    def test_network_filesystems_are_reported(self):
        results = [
            result("/var/lib/infinito/proof", "nfs4"),
            result("/opt/local", "ext4"),
            result("/mnt/share", "cifs"),
            result("/mnt/remote", "fuse.sshfs"),
        ]
        self.assertEqual(
            module.network_filesystems(results),
            [
                "/var/lib/infinito/proof (nfs4)",
                "/mnt/share (cifs)",
                "/mnt/remote (fuse.sshfs)",
            ],
        )

    def test_every_listed_type_is_refused(self):
        for fstype in module.NETWORK_FSTYPES:
            with self.subTest(fstype=fstype):
                self.assertEqual(
                    len(module.network_filesystems([result("/x", fstype)])), 1
                )

    def test_no_checkouts(self):
        self.assertEqual(module.network_filesystems([]), [])


if __name__ == "__main__":
    unittest.main()
