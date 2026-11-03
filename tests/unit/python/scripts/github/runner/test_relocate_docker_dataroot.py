from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "runner" / "relocate_docker_dataroot.sh"
MIN_FREE_GB = "75"
DUMP_V2 = "version = 3\nroot = '/var/lib/containerd'\nstate = '/run/containerd'\n"
DUMP_V1 = 'version = 2\nroot = "/var/lib/containerd"\nstate = "/run/containerd"\n'
STOP = "systemctl stop docker.socket docker.service containerd.service"
BIND = "mount --bind /mnt/containerd /var/lib/containerd"
UNBIND = "umount /var/lib/containerd"
RESTART = "systemctl start containerd.service docker.socket docker.service"

SUDO_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$*" >>"${STUB_LOG}"\n'
    'if [ -x "${STUB_BIN}/$1" ]; then exec "${STUB_BIN}/$1" "${@:2}"; fi\n'
    'echo "unstubbed sudo $1" >&2\n'
    "exit 97\n"
)
UNPRIVILEGED_STUB = (
    '#!/usr/bin/env bash\necho "$(basename "$0") ran without sudo" >&2\nexit 98\n'
)
TERM_HOOK = (
    'if [ "$(basename "$0")" = "${STUB_TERM_ON}" ]; then kill -TERM "${PPID}"; fi\n'
)
UNPRIVILEGED = {
    "mountpoint": (
        "#!/usr/bin/env bash\n"
        'case "${*: -1}" in\n'
        '/mnt) [ "${STUB_MNT_MOUNTED}" = 1 ] ;;\n'
        '/var/lib/containerd) [ -e "${STUB_STATE}/bound" ] ;;\n'
        "*) exit 1 ;;\n"
        "esac\n"
    ),
    "df": (
        "#!/usr/bin/env bash\n"
        'echo "Avail"\n'
        'if [ "${*: -1}" = /mnt ]; then echo "${STUB_MNT_FREE}"; '
        'else echo "${STUB_ROOT_FREE}"; fi\n'
    ),
    "systemctl": '#!/usr/bin/env bash\nexit "${STUB_CONTAINERD_UNIT_RC}"\n',
    "docker": (
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        'ps) printf "%s" "${STUB_CONTAINERS}" ;;\n'
        'images) printf "%s" "${STUB_IMAGES}" ;;\n'
        'volume) printf "%s" "${STUB_VOLUMES}" ;;\n'
        'system) printf "Images=0\\nContainers=0\\nLocal Volumes=0\\n'
        'Build Cache=%s\\n" "${STUB_BUILD_CACHE}" ;;\n'
        'info) echo "${STUB_DOCKER_ROOT}" ;;\n'
        "*) exit 96 ;;\n"
        "esac\n"
    ),
    "stat": (
        "#!/usr/bin/env bash\n"
        'case "${*: -1}" in\n'
        "/mnt) echo 2049 ;;\n"
        '/mnt/docker-host) echo "${STUB_DOCKER_ROOT_DEV}" ;;\n'
        "*) echo 66305 ;;\n"
        "esac\n"
    ),
    "pgrep": '#!/usr/bin/env bash\nprintf "%s" "${STUB_SHIMS}"\nexit "${STUB_SHIM_RC}"\n',
}
PRIVILEGED = {
    "systemctl": (
        "#!/usr/bin/env bash\n"
        'if [ "$1" = status ]; then exit "${STUB_STATUS_RC}"; fi\n'
        'if [ "$*" = "${STUB_FAIL_SYSTEMCTL}" ]; then exit 1; fi\n'
    ),
    "containerd": '#!/usr/bin/env bash\nprintf "%s" "${STUB_CONTAINERD_DUMP}"\n',
    "ctr": (
        "#!/usr/bin/env bash\n"
        'if [ "$1" = namespaces ]; then printf "%s" "${STUB_NAMESPACES}"; exit; fi\n'
        'if [ "$1" = -n ] && [ "$2" = "${STUB_FOREIGN_NS}" ]; then\n'
        '  if [ "$3" = containers ]; then printf "%s" "${STUB_FOREIGN_CONTAINERS}"; fi\n'
        '  if [ "$3" = tasks ]; then printf "%s" "${STUB_FOREIGN_TASKS}"; fi\n'
        "fi\n"
    ),
    "du": '#!/usr/bin/env bash\nprintf "1.2G\\t%s\\n" "${*: -1}"\n',
    "true": '#!/usr/bin/env bash\nexit "${STUB_SUDO_RC}"\n',
    "test": (
        "#!/usr/bin/env bash\n"
        'if [ "$1" = -e ]; then [ "${STUB_DAEMON_EXISTS}" = 1 ]; exit; fi\n'
        '[ "${STUB_METADATA}" = 1 ]\n'
    ),
    "cat": (
        "#!/usr/bin/env bash\n"
        'if [ "${STUB_DAEMON_CAT_RC}" != 0 ]; then exit "${STUB_DAEMON_CAT_RC}"; fi\n'
        'printf "%s" "${STUB_DAEMON_IN}"\n'
    ),
    "mkdir": "#!/usr/bin/env bash\n" + TERM_HOOK,
    "mount": (
        "#!/usr/bin/env bash\n"
        'if [ "${STUB_MOUNT_RC}" != 0 ]; then exit "${STUB_MOUNT_RC}"; fi\n'
        'touch "${STUB_STATE}/bound"\n'
    ),
    "umount": '#!/usr/bin/env bash\nrm -f "${STUB_STATE}/bound"\n',
    "install": '#!/usr/bin/env bash\ncp "${*: -2:1}" "${STUB_DAEMON_OUT}"\n',
    "rm": '#!/usr/bin/env bash\n/bin/rm -f "${STUB_DAEMON_OUT}"\n',
    "journalctl": "#!/usr/bin/env bash\nexit 0\n",
}
DESTRUCTIVE = ("mount", "umount", "install", "ctr", "containerd", "journalctl", "mkdir")


@dataclass
class Runner:
    """The faked runner state relocate_docker_dataroot.sh meets.

    Args:
        runner_environment: RUNNER_ENVIRONMENT, None to leave it unset.
        act: ACT, None to leave it unset.
        skip: SKIP_DOCKER_RELOCATE, None to leave it unset.
        mounted: whether /mnt is a separate mount.
        mnt_free: GB df reports free on /mnt.
        root_free: GB df reports free on /.
        dump: what ``containerd config dump`` prints.
        containerd_unit_rc: exit code of ``systemctl cat containerd.service``.
        containers: what ``docker ps -aq`` prints.
        images: what ``docker images -q`` prints.
        volumes: what ``docker volume ls -q`` prints.
        build_cache: Build Cache record count in ``docker system df``.
        namespaces: what ``ctr namespaces ls -q`` prints.
        foreign_ns: namespace whose containers and tasks are faked.
        foreign_containers: containers in foreign_ns.
        foreign_tasks: tasks in foreign_ns.
        shims: what ``pgrep -a containerd-shim`` prints.
        shim_rc: exit code of pgrep (1 means no shim).
        sudo_rc: exit code of ``sudo true``.
        daemon_exists: whether daemon.json exists.
        daemon_in: content of the existing daemon.json.
        daemon_cat_rc: exit code of ``sudo cat`` on daemon.json.
        mount_rc: exit code of the bind mount.
        fail_systemctl: the one systemctl argument string that fails.
        status_rc: exit code of ``systemctl status``.
        term_on: privileged stub that sends SIGTERM to the script.
        metadata: whether containerd's meta.db shows up under /mnt/containerd.
        docker_root: what ``docker info`` reports as DockerRootDir.
        docker_root_dev: device id stat reports for /mnt/docker-host.
        min_free_gb: the MIN_FREE_GB argument.
    """

    runner_environment: str | None = "github-hosted"
    act: str | None = None
    skip: str | None = None
    mounted: bool = True
    mnt_free: int = 137
    root_free: int = 51
    dump: str = DUMP_V2
    containerd_unit_rc: int = 0
    containers: str = ""
    images: str = ""
    volumes: str = ""
    build_cache: str = "0"
    namespaces: str = "moby\n"
    foreign_ns: str = "k8s.io"
    foreign_containers: str = ""
    foreign_tasks: str = ""
    shims: str = ""
    shim_rc: int = 1
    sudo_rc: int = 0
    daemon_exists: bool = False
    daemon_in: str = ""
    daemon_cat_rc: int = 0
    mount_rc: int = 0
    fail_systemctl: str = ""
    status_rc: int = 0
    term_on: str = ""
    metadata: bool = True
    docker_root: str = "/mnt/docker-host"
    docker_root_dev: str = "2049"
    min_free_gb: str = MIN_FREE_GB
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Outcome:
    """What a relocation run left behind.

    Args:
        done: the finished script.
        calls: every privileged call in order.
        daemon: the daemon.json on disk afterwards, None when there is none
            or it is no valid JSON.
        daemon_raw: the daemon.json bytes on disk afterwards, None when there is none.
        bound: whether the containerd bind mount is still in place.
    """

    done: subprocess.CompletedProcess
    calls: list[str]
    daemon: dict | None
    daemon_raw: str | None
    bound: bool


def relocate(runner: Runner) -> Outcome:
    """Run relocate_docker_dataroot.sh against a faked runner.

    Args:
        runner: the faked services, disks and files.

    Returns:
        The outcome of the run.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runner_dir = root / "runner"
        bin_dir = root / "bin"
        stub_bin = root / "privileged"
        state = root / "state"
        for directory in (runner_dir, bin_dir, stub_bin, state):
            directory.mkdir()
        (runner_dir / "relocate_docker_dataroot.sh").symlink_to(SCRIPT)
        stubs = [(runner_dir / "dump_state.sh", "#!/usr/bin/env bash\nexit 0\n")]
        stubs += [(bin_dir / "sudo", SUDO_STUB)]
        stubs += [(bin_dir / name, UNPRIVILEGED_STUB) for name in DESTRUCTIVE]
        stubs += [(bin_dir / name, body) for name, body in UNPRIVILEGED.items()]
        stubs += [(stub_bin / name, body) for name, body in PRIVILEGED.items()]
        for path, body in stubs:
            path.write_text(body)
            path.chmod(0o755)
        log = root / "calls.log"
        log.touch()
        daemon_out = root / "daemon.json"
        if runner.daemon_exists:
            daemon_out.write_text(runner.daemon_in)
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in ("BASH_ENV", "ACT", "RUNNER_ENVIRONMENT", "SKIP_DOCKER_RELOCATE")
        }
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_BIN=str(stub_bin),
            STUB_STATE=str(state),
            STUB_MNT_MOUNTED="1" if runner.mounted else "0",
            STUB_MNT_FREE=str(runner.mnt_free),
            STUB_ROOT_FREE=str(runner.root_free),
            STUB_CONTAINERD_DUMP=runner.dump,
            STUB_CONTAINERD_UNIT_RC=str(runner.containerd_unit_rc),
            STUB_CONTAINERS=runner.containers,
            STUB_IMAGES=runner.images,
            STUB_VOLUMES=runner.volumes,
            STUB_BUILD_CACHE=runner.build_cache,
            STUB_NAMESPACES=runner.namespaces,
            STUB_FOREIGN_NS=runner.foreign_ns,
            STUB_FOREIGN_CONTAINERS=runner.foreign_containers,
            STUB_FOREIGN_TASKS=runner.foreign_tasks,
            STUB_SHIMS=runner.shims,
            STUB_SHIM_RC=str(runner.shim_rc),
            STUB_SUDO_RC=str(runner.sudo_rc),
            STUB_DAEMON_EXISTS="1" if runner.daemon_exists else "0",
            STUB_DAEMON_IN=runner.daemon_in,
            STUB_DAEMON_CAT_RC=str(runner.daemon_cat_rc),
            STUB_DAEMON_OUT=str(daemon_out),
            STUB_MOUNT_RC=str(runner.mount_rc),
            STUB_FAIL_SYSTEMCTL=runner.fail_systemctl,
            STUB_STATUS_RC=str(runner.status_rc),
            STUB_TERM_ON=runner.term_on,
            STUB_METADATA="1" if runner.metadata else "0",
            STUB_DOCKER_ROOT=runner.docker_root,
            STUB_DOCKER_ROOT_DEV=runner.docker_root_dev,
            **runner.extra,
        )
        optional = {
            "RUNNER_ENVIRONMENT": runner.runner_environment,
            "ACT": runner.act,
            "SKIP_DOCKER_RELOCATE": runner.skip,
        }
        env.update({k: v for k, v in optional.items() if v is not None})
        done = subprocess.run(
            [
                "bash",
                str(runner_dir / "relocate_docker_dataroot.sh"),
                runner.min_free_gb,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = log.read_text().splitlines()  # nocheck: cache-read  stub call log
        content = (
            daemon_out.read_text()  # nocheck: cache-read  stub output
            if daemon_out.exists()
            else None
        )
        try:
            daemon = json.loads(content) if content else None
        except json.JSONDecodeError:
            daemon = None
        return Outcome(
            done=done,
            calls=calls,
            daemon=daemon,
            daemon_raw=content,
            bound=(state / "bound").exists(),
        )


class TestRelocation(unittest.TestCase):
    def test_small_shape_moves_containerd_and_docker_onto_the_spare_disk(self) -> None:
        out = relocate(Runner())
        self.assertEqual(out.done.returncode, 0, out.done.stderr)
        stop, bind = out.calls.index(STOP), out.calls.index(BIND)
        start = out.calls.index("systemctl start containerd.service")
        self.assertLess(stop, bind)
        self.assertLess(bind, start)
        self.assertIn("systemctl start docker.socket docker.service", out.calls)
        self.assertIn(
            "test -f /mnt/containerd/io.containerd.metadata.v1.bolt/meta.db", out.calls
        )
        self.assertEqual(out.daemon, {"data-root": "/mnt/docker-host"})
        self.assertTrue(out.bound)

    def test_containerd_1x_dump_with_double_quotes_is_understood(self) -> None:
        out = relocate(Runner(dump=DUMP_V1))
        self.assertEqual(out.done.returncode, 0, out.done.stderr)
        self.assertIn(BIND, out.calls)

    def test_existing_daemon_json_keeps_its_settings(self) -> None:
        out = relocate(Runner(daemon_exists=True, daemon_in='{"debug": true}'))
        self.assertEqual(out.done.returncode, 0, out.done.stderr)
        self.assertEqual(out.daemon, {"debug": True, "data-root": "/mnt/docker-host"})


class TestDeclines(unittest.TestCase):
    def assert_declined(self, out: Outcome, reason: str) -> None:
        """Assert a visible no-op: exit 0, a notice with the reason, no call.

        Args:
            out: the outcome of the run.
            reason: text the notice must carry.
        """
        self.assertEqual(out.done.returncode, 0, out.done.stderr)
        self.assertIn("::notice::", out.done.stdout)
        self.assertIn(reason, out.done.stdout)
        self.assertEqual(out.calls, [])

    def test_large_shape_without_a_mnt_mount(self) -> None:
        self.assert_declined(
            relocate(Runner(mounted=False)), "/mnt is not a separate mount"
        )

    def test_self_hosted_runner(self) -> None:
        self.assert_declined(
            relocate(Runner(runner_environment="self-hosted")),
            "not a GitHub-hosted runner",
        )

    def test_unknown_runner_environment(self) -> None:
        self.assert_declined(
            relocate(Runner(runner_environment=None)), "not a GitHub-hosted runner"
        )

    def test_mnt_below_the_floor(self) -> None:
        self.assert_declined(relocate(Runner(mnt_free=60, root_free=20)), "below 75G")

    def test_mnt_not_roomier_than_root(self) -> None:
        self.assert_declined(
            relocate(Runner(mnt_free=80, root_free=90)), "not more than"
        )

    def test_skip_toggle(self) -> None:
        self.assert_declined(relocate(Runner(skip="1")), "SKIP_DOCKER_RELOCATE=1")


class TestRefusalsBeforeTheStop(unittest.TestCase):
    def assert_refused(self, out: Outcome, reason: str) -> None:
        """Assert a loud refusal before anything was stopped or written.

        Args:
            out: the outcome of the run.
            reason: text the error must carry.
        """
        self.assertEqual(out.done.returncode, 1)
        self.assertIn(reason, out.done.stderr)
        self.assertNotIn(STOP, out.calls)
        self.assertFalse([c for c in out.calls if c.startswith(("mount ", "install "))])
        self.assertFalse(out.bound)

    def test_act_even_with_a_faked_github_runner(self) -> None:
        for act in ("true", "1"):
            with self.subTest(act=act):
                self.assert_refused(
                    relocate(Runner(act=act)), "refuses to run under act"
                )

    def test_non_numeric_floor(self) -> None:
        self.assert_refused(relocate(Runner(min_free_gb="forty")), "positive integer")

    def test_missing_containerd_unit(self) -> None:
        self.assert_refused(
            relocate(Runner(containerd_unit_rc=1)), "containerd.service is missing"
        )

    def test_containerd_root_elsewhere(self) -> None:
        self.assert_refused(
            relocate(Runner(dump="version = 3\nroot = '/data/containerd'\n")),
            "/data/containerd",
        )

    def test_existing_containers(self) -> None:
        self.assert_refused(relocate(Runner(containers="abc123\n")), "abc123")

    def test_existing_images(self) -> None:
        self.assert_refused(relocate(Runner(images="sha256feed\n")), "sha256feed")

    def test_existing_volumes(self) -> None:
        self.assert_refused(
            relocate(Runner(volumes="core_infinito\n")), "core_infinito"
        )

    def test_existing_build_cache(self) -> None:
        self.assert_refused(relocate(Runner(build_cache="3")), "build cache")

    def test_containers_in_another_namespace(self) -> None:
        out = relocate(
            Runner(namespaces="moby\nk8s.io\n", foreign_containers="pause1\n")
        )
        self.assert_refused(out, "k8s.io holds containers: pause1")

    def test_tasks_in_another_namespace(self) -> None:
        out = relocate(Runner(namespaces="moby\nk8s.io\n", foreign_tasks="task7\n"))
        self.assert_refused(out, "k8s.io runs tasks: task7")

    def test_running_shims(self) -> None:
        out = relocate(Runner(shims="4242 containerd-shim-runc-v2 -id x\n", shim_rc=0))
        self.assert_refused(out, "containerd shims are running")

    def test_shim_listing_error(self) -> None:
        self.assert_refused(
            relocate(Runner(shim_rc=2)), "could not list containerd shims"
        )

    def test_broken_sudo(self) -> None:
        out = relocate(Runner(sudo_rc=1))
        self.assertEqual(out.done.returncode, 1)
        self.assertNotIn(STOP, out.calls)

    def test_unreadable_daemon_json_is_never_overwritten(self) -> None:
        out = relocate(Runner(daemon_exists=True, daemon_in="{}", daemon_cat_rc=1))
        self.assertEqual(out.done.returncode, 1)
        self.assertNotIn(STOP, out.calls)
        self.assertFalse([c for c in out.calls if c.startswith("install ")])
        self.assertEqual(out.daemon, {})

    def test_invalid_daemon_json_is_never_overwritten(self) -> None:
        out = relocate(Runner(daemon_exists=True, daemon_in="{not json"))
        self.assertEqual(out.done.returncode, 1)
        self.assertIn("is not valid JSON", out.done.stderr)
        self.assertNotIn(STOP, out.calls)
        self.assertFalse([c for c in out.calls if c.startswith("install ")])
        self.assertEqual(out.daemon_raw, "{not json")


class TestRollback(unittest.TestCase):
    def assert_rolled_back(self, out: Outcome, reason: str) -> None:
        """Assert the rollback: no bind left, daemons restarted last, exit 1.

        Args:
            out: the outcome of the run.
            reason: text the rollback error must carry.
        """
        self.assertEqual(out.done.returncode, 1, out.done.stderr)
        self.assertIn("rolling Docker and containerd back onto /", out.done.stderr)
        self.assertIn(reason, out.done.stderr)
        self.assertFalse(out.bound)
        self.assertIn(RESTART, out.calls)
        self.assertTrue([c for c in out.calls if c.startswith("journalctl ")])

    def test_failed_bind_mount_removes_the_daemon_json_it_never_had(self) -> None:
        out = relocate(Runner(mount_rc=32))
        self.assert_rolled_back(out, "mount --bind")
        self.assertIsNone(out.daemon)

    def test_failed_containerd_start_unbinds_before_the_restart(self) -> None:
        out = relocate(
            Runner(
                daemon_exists=True,
                daemon_in='{"debug": true}',
                fail_systemctl="start containerd.service",
            )
        )
        self.assert_rolled_back(out, "systemctl start containerd.service")
        self.assertLess(out.calls.index(UNBIND), len(out.calls) - 1)
        self.assertLess(out.calls.index(UNBIND), out.calls.index(RESTART))
        self.assertEqual(out.daemon, {"debug": True})

    def test_cancel_during_the_move_rolls_back(self) -> None:
        out = relocate(Runner(term_on="mkdir"))
        self.assert_rolled_back(out, "interrupted")

    def test_down_units_still_yield_the_journal(self) -> None:
        out = relocate(Runner(mount_rc=32, status_rc=3))
        self.assert_rolled_back(out, "mount --bind")

    def test_containerd_without_metadata_on_the_spare_disk(self) -> None:
        out = relocate(Runner(metadata=False))
        self.assert_rolled_back(out, "without its metadata")
        self.assertIn(UNBIND, out.calls)
        self.assertIsNone(out.daemon)

    def test_docker_root_elsewhere(self) -> None:
        out = relocate(Runner(docker_root="/var/lib/docker"))
        self.assert_rolled_back(out, "expected '/mnt/docker-host'")

    def test_docker_root_off_the_spare_disk(self) -> None:
        out = relocate(Runner(docker_root_dev="66305"))
        self.assert_rolled_back(out, "not on the /mnt filesystem")


if __name__ == "__main__":
    unittest.main()
