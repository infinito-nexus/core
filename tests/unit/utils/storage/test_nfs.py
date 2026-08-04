import unittest

from utils.storage.nfs import (
    client_src,
    fstype,
    mount_opts,
    state_path,
    swarm_nfs_backed,
)


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
            self.assertEqual(mount_opts(4, rt), "vers=4,rw,soft,timeo=50,retrans=3")

    def test_mount_opts_prod_hard(self):
        self.assertEqual(mount_opts(4, "host"), "vers=4,rw,hard,timeo=600")

    def test_mount_opts_v4_carries_no_v3_locking_token(self):
        self.assertNotIn("local_lock", mount_opts(4, "host"))
        self.assertNotIn("nolock", mount_opts(4, "host"))

    def test_mount_opts_v3_still_disables_nlm(self):
        self.assertEqual(mount_opts(3, "host"), "vers=3,rw,hard,timeo=600,nolock")

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


class TestSwarmNfsBacked(unittest.TestCase):
    """The predicate mirrors the compose_volumes rewrite decision: swarm mode
    with an nfs backend backs every volume of a non-manager-pinned role unless
    the entry opts out with ``nfs: false``. web-app-nextcloud carries no
    placement pin; web-app-seaweedfs is pinned to the manager on purpose."""

    def test_backed_in_swarm_with_nfs(self):
        self.assertTrue(
            swarm_nfs_backed(
                {"name": "nextcloud_data"},
                application_id="web-app-nextcloud",
                deployment_mode="swarm",
                storage_backend="nfs",
            )
        )

    def test_compose_mode_never_backs(self):
        self.assertFalse(
            swarm_nfs_backed(
                {"name": "nextcloud_data"},
                application_id="web-app-nextcloud",
                deployment_mode="compose",
                storage_backend="nfs",
            )
        )

    def test_local_backend_never_backs(self):
        self.assertFalse(
            swarm_nfs_backed(
                {"name": "nextcloud_data"},
                application_id="web-app-nextcloud",
                deployment_mode="swarm",
                storage_backend="local",
            )
        )

    def test_a_manager_pinned_role_stays_node_local(self):
        self.assertFalse(
            swarm_nfs_backed(
                {"name": "seaweedfs_data"},
                application_id="web-app-seaweedfs",
                deployment_mode="swarm",
                storage_backend="nfs",
            )
        )

    def test_nfs_false_opts_out(self):
        self.assertFalse(
            swarm_nfs_backed(
                {"name": "gitaly_repos", "nfs": False},
                application_id="web-app-gitlab",
                deployment_mode="swarm",
                storage_backend="nfs",
            )
        )

    def test_a_role_forcing_compose_is_not_backed(self):
        """web-app-bigbluebutton pins compose_mode_force: compose in its vars,
        so the rewrite leaves its volumes node-local even in a swarm cluster."""
        self.assertFalse(
            swarm_nfs_backed(
                {"name": "bigbluebutton_database"},
                application_id="web-app-bigbluebutton",
                deployment_mode="swarm",
                storage_backend="nfs",
            )
        )

    def test_an_unresolvable_force_expression_is_not_backed(self):
        """web-app-matrix computes compose_mode_force from a config lookup. A
        mode this predicate cannot resolve statically must keep the volume in
        the volume backup rather than drop it from both capture paths."""
        self.assertFalse(
            swarm_nfs_backed(
                {"name": "matrix_mdad_matrix"},
                application_id="web-app-matrix",
                deployment_mode="swarm",
                storage_backend="nfs",
            )
        )


if __name__ == "__main__":
    unittest.main()
