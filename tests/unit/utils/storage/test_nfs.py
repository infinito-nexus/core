import unittest

from utils.storage.nfs import client_src, fstype, mount_opts, state_path


class TestNfsHelpers(unittest.TestCase):
    def test_state_path(self):
        self.assertEqual(
            state_path("/srv/nfs", "infinito-state"), "/srv/nfs/infinito-state"
        )

    def test_fstype(self):
        self.assertEqual(fstype(4), "nfs4")
        self.assertEqual(fstype("4"), "nfs4")
        self.assertEqual(fstype(3), "nfs")

    def test_mount_opts_lab_runtimes_soft(self):
        for rt in ("dev", "act", "github"):
            self.assertEqual(
                mount_opts(4, rt), "vers=4,rw,soft,timeo=50,retrans=3,local_lock=flock"
            )

    def test_mount_opts_prod_hard(self):
        self.assertEqual(
            mount_opts(4, "host"), "vers=4,rw,hard,timeo=600,local_lock=flock"
        )

    def test_client_src_kernel_v4_is_root(self):
        self.assertEqual(
            client_src("1.2.3.4", 4, "kernel", "/srv/nfs/infinito-state"), "1.2.3.4:/"
        )

    def test_client_src_ganesha_is_full_path(self):
        self.assertEqual(
            client_src("1.2.3.4", 4, "ganesha", "/srv/nfs/infinito-state"),
            "1.2.3.4:/srv/nfs/infinito-state",
        )

    def test_client_src_v3_is_full_path(self):
        self.assertEqual(
            client_src("1.2.3.4", 3, "kernel", "/srv/nfs/infinito-state"),
            "1.2.3.4:/srv/nfs/infinito-state",
        )


if __name__ == "__main__":
    unittest.main()
