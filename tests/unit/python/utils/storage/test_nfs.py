import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES
from utils.storage.nfs import (
    client_src,
    fstype,
    mount_opts,
    nested_tmpfs_mountpoints,
    state_path,
    swarm_nfs_backed,
    volume_dir,
)


def _role_volumes(application_id):
    """Return a role's ``meta/volumes.yml`` mapping.

    Args:
        application_id: the role whose file is read.
    """
    path = PROJECT_ROOT / "roles" / application_id / ROLE_FILE_META_VOLUMES
    return load_yaml_str(read_text(str(path)))


def _every_volume_on_nfs(volumes_meta):
    """Return the NFS directory of every volume that does not opt out of NFS.

    Args:
        volumes_meta: a ``meta/volumes.yml`` mapping.
    """
    return {
        name: volume_dir(name, entry)
        for name, entry in volumes_meta.items()
        if entry.get("type", "volume") == "volume" and entry.get("nfs") is not False
    }


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
                mount_opts(4, rt), "vers=4,rw,noresvport,soft,timeo=50,retrans=3"
            )

    def test_mount_opts_prod_hard(self):
        self.assertEqual(mount_opts(4, "host"), "vers=4,rw,noresvport,hard,timeo=600")

    def test_mount_opts_keep_the_client_off_published_privileged_ports(self):
        """A reserved source port can land on imaps/993 or pop3s/995 and then
        blocks the whole ingress port set of the mail stack."""
        for version in (3, 4):
            for runtime in ("dev", "act", "github", "host"):
                self.assertIn("noresvport", mount_opts(version, runtime))

    def test_mount_opts_v4_carries_no_v3_locking_token(self):
        self.assertNotIn("local_lock", mount_opts(4, "host"))
        self.assertNotIn("nolock", mount_opts(4, "host"))

    def test_mount_opts_v3_still_disables_nlm(self):
        self.assertEqual(
            mount_opts(3, "host"), "vers=3,rw,noresvport,hard,timeo=600,nolock"
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

    def test_volume_dir_is_the_pinned_name(self):
        self.assertEqual(
            volume_dir("whiteboard_tmp", {"name": "nextcloud_whiteboard_tmp"}),
            "nextcloud_whiteboard_tmp",
        )

    def test_volume_dir_falls_back_to_the_key_without_a_pin(self):
        self.assertEqual(volume_dir("docs_sites", {"backup": False}), "docs_sites")


class TestSwarmNfsBacked(unittest.TestCase):
    """The predicate mirrors the compose_volumes rewrite decision: swarm mode
    with an nfs backend backs every volume of a non-manager-pinned role unless
    the entry opts out with ``nfs: false``. web-app-nextcloud carries no
    placement pin; web-svc-seaweedfs is pinned to the manager on purpose."""

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
                application_id="web-svc-seaweedfs",
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


class TestNestedTmpfsMountpoints(unittest.TestCase):
    def test_weblate_static_mountpoint_carries_the_tmpfs_mode(self):
        volumes = _role_volumes("web-app-weblate")
        self.assertEqual(
            nested_tmpfs_mountpoints(volumes, _every_volume_on_nfs(volumes)),
            [{"path": "weblate_cache/static", "mode": 0o1777}],
            "the static tmpfs of weblate, beat and worker sits inside the "
            "weblate_cache volume; its mountpoint directory must exist with mode "
            "1777 before the stack deploys, or uid 1000 cannot collectstatic",
        )

    def test_matrix_mautrix_workdir_is_not_nested_in_its_own_services_volume(self):
        volumes = _role_volumes("web-app-matrix")
        self.assertEqual(
            nested_tmpfs_mountpoints(volumes, _every_volume_on_nfs(volumes)),
            [],
            "the mautrix tmpfs at /data shares its target with synapse_data, but "
            "only synapse mounts that volume",
        )

    def test_a_sibling_path_is_not_nested(self):
        volumes = {
            "cache": {
                "type": "volume",
                "mounts": [{"service": "app", "target": "/app/cache"}],
            },
            "scratch": {
                "type": "tmpfs",
                "mounts": [{"service": "app", "target": "/app/cachex"}],
            },
        }
        self.assertEqual(nested_tmpfs_mountpoints(volumes, {"cache": "app_cache"}), [])

    def test_the_innermost_volume_holds_the_mountpoint(self):
        volumes = {
            "app": {
                "type": "volume",
                "mounts": [{"service": "app", "target": "/app"}],
            },
            "cache": {
                "type": "volume",
                "mounts": [{"service": "app", "target": "/app/cache/"}],
            },
            "static": {
                "type": "tmpfs",
                "mounts": [
                    {"service": "app", "target": "/app/cache/static", "mode": "0700"}
                ],
            },
        }
        nfs_dirs = {"app": "app_app", "cache": "app_cache"}
        self.assertEqual(
            nested_tmpfs_mountpoints(volumes, nfs_dirs),
            [{"path": "app_cache/static", "mode": 0o700}],
        )

    def test_a_nested_tmpfs_without_mode_fails_loudly(self):
        volumes = {
            "cache": {
                "type": "volume",
                "mounts": [{"service": "app", "target": "/app/cache"}],
            },
            "static": {
                "type": "tmpfs",
                "mounts": [{"service": "app", "target": "/app/cache/static"}],
            },
        }
        with self.assertRaisesRegex(ValueError, "declares no 'mode'"):
            nested_tmpfs_mountpoints(volumes, {"cache": "app_cache"})

    def test_every_role_declares_a_mode_on_its_nested_tmpfs_mounts(self):
        for path in sorted(
            (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_VOLUMES}")
        ):
            volumes = load_yaml_str(read_text(str(path)))
            if not isinstance(volumes, dict):
                continue
            with self.subTest(role=path.parent.parent.name):
                nested_tmpfs_mountpoints(volumes, _every_volume_on_nfs(volumes))


if __name__ == "__main__":
    unittest.main()
