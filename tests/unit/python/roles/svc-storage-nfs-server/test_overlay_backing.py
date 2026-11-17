"""When the export base gets its ext4 loopback backing."""

from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

TASKS = (
    PROJECT_ROOT
    / "roles"
    / "svc-storage-nfs-server"
    / "tasks"
    / "02_overlay_backing.yml"
)
LOOP_INCLUDE = "02_overlay_backing/ext4_loop.yml"
RUNTIMES = ("host", "dev", "act", "github")


def _backs_the_export_base(*, fstype: str, runtime: str) -> bool:
    """Evaluate the loopback include's ``when`` the way Ansible would.

    Args:
        fstype: what ``findmnt -no FSTYPE`` reports for the export base.
        runtime: the deploy's ``RUNTIME``.

    Returns:
        True when every condition of the include holds.
    """
    tasks = load_yaml_any(str(TASKS))
    include = next(
        task
        for task in tasks
        if task.get("ansible.builtin.include_tasks") == LOOP_INCLUDE
    )
    conditions = include.get("when", [])
    if isinstance(conditions, str):
        conditions = [conditions]
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    facts = {
        "_nfs_export_base_fstype": {"stdout": f"{fstype}\n"},
        "RUNTIME": runtime,
    }
    return all(env.compile_expression(condition)(**facts) for condition in conditions)


class TestOverlayBacking(unittest.TestCase):
    def test_an_overlay_export_base_is_backed_on_every_runtime(self):
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                self.assertTrue(
                    _backs_the_export_base(fstype="overlay", runtime=runtime),
                    "ganesha FSAL_VFS gets no file handle on overlayfs (vfs_lookup_path "
                    "'Operation not supported', init_export_root ExportId=2), so every "
                    "client mount of /srv/nfs/infinito-state answers 'No such file or "
                    "directory'; the docs CLI replay deploys with RUNTIME=host into the "
                    "overlay-rooted shared target and failed exactly so in CI run "
                    "43777013536 (NFS Server #1)",
                )

    def test_a_real_filesystem_is_left_alone(self):
        for fstype in ("ext4", "xfs", "btrfs", "zfs"):
            for runtime in RUNTIMES:
                with self.subTest(fstype=fstype, runtime=runtime):
                    self.assertFalse(
                        _backs_the_export_base(fstype=fstype, runtime=runtime),
                        f"an export base on {fstype} exports as it is",
                    )


if __name__ == "__main__":
    unittest.main()
