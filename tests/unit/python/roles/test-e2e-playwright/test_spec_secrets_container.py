from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest.mock
from pathlib import Path

from ._spec_secrets_fakes import (
    IMAGE,
    MASKER,
    STAGE_ENV,
    STAGE_KEYS,
    TOUCH,
    VALUE,
    container_argv,
    exec_tool,
    install,
    load_from,
    make_run,
    without_docker_config,
)
from ._spec_secrets_wiring import (
    ARGV_VARS,
    PATH_FACT,
    TEMPLATE_EXISTS,
    environment,
    flattened,
    mount_violations,
    render,
    run_argv,
)

FOREIGN_IMAGE = "mcr.microsoft.com/playwright:v0.0.1-noble"
UNCHECKED = ("        check_container(container, paths[0])\n", "")
UNDECLARED = ("(key not in declared or RUNTIME.match(key))", "RUNTIME.match(key)")
KEYS_SOURCE = (
    "APP_BASE_URL={{ a }}\n{% if b %}\nADMIN_USERNAME={{ c }}\n{% endif %}\n"
    "{{ d }}=e\nAPP_BASE_URL=f\n"
)
QUEUED = ["--name=infinito-playwright-web-app-x", "--oom-score-adj=500"]
WRITABLE = "a run with the template may write into the stage dir"
ENV_TRIGGERS = {
    "node_options": "NODE_OPTIONS=--require=/e2e/x.js",
    "bash_env": "BASH_ENV=/e2e/x.sh",
    "source_transform": "PW_TEST_SOURCE_TRANSFORM=/e2e/t.js",
    "remote_browser": "PW_TEST_CONNECT_WS_ENDPOINT=ws://203.0.113.9:3000",
    "debug_file": "DEBUG_FILE=/e2e/leak.log",
    "browsers_path": "PLAYWRIGHT_BROWSERS_PATH=/e2e/browsers",
    "float_timeout": "PLAYWRIGHT_TEST_TIMEOUT=6e4",
    "host_copy": "NODE_OPTIONS",
    "undeclared": "FOO=bar",
}


def env_refused(line: str, *replacements, keys: str | None) -> bool:
    """Hold a container command whose env file adds one line against the check.

    Args:
        line: the line the stage ``.env`` gets behind ``STAGE_ENV``.
        *replacements: changes to the container check, for a negative control.
        keys: the stage ``.env.keys``, None for none.

    Returns:
        Whether ``check_container`` refused it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        module = load_from(root / "bin", root, *replacements)
        run = root / "run"
        argv = container_argv(root, run)
        stage = root / "stage"
        (stage / ".env").write_text(f"{STAGE_ENV}{line}\n", encoding="utf-8")
        (stage / ".env.keys").unlink()
        if keys is not None:
            (stage / ".env.keys").write_text(keys, encoding="utf-8")
        try:
            with without_docker_config():
                module.check_container(argv, run)
        except module.spec_secrets.SpecSecretsError:
            return True
        return False


def open_config(root: Path) -> Path:
    """Make a Docker config dir any user may write, which the masker refuses.

    Args:
        root: the scratch dir.

    Returns:
        The dir, mode 0777 whoever runs the test.
    """
    docker = root / "docker-config"
    docker.mkdir(exist_ok=True)
    docker.chmod(0o777)
    return docker


def listed_keys(source: str) -> tuple[list[str], str, list[str]]:
    """Render the task that lists the keys an env template declares.

    Args:
        source: the env template's source, as ``lookup('file')`` reads it.

    Returns:
        The listed keys, the file the task writes and the conditions it and
        its block run under.
    """
    task = next(t for t in flattened("03_run_pass.yml") if t["name"].startswith("📇"))
    copied = task["ansible.builtin.copy"]
    text = (
        environment()
        .from_string(copied["content"])
        .render(
            lookup=lambda kind, path: source if (kind, path) == ("file", "T") else "",
            _playwright_env_template="T",
        )
    )
    keys = [line.strip() for line in text.splitlines() if line.strip()]
    return keys, copied["dest"], task.get("when", [])


def argv_triggers(stage: Path, run: Path) -> dict[str, tuple[str, list[str]]]:
    """Name each change of the container command a run with spec secrets must refuse.

    Args:
        stage: the stage dir ``container_argv`` made.
        run: the run directory.

    Returns:
        Per trigger, the word of ``container_argv`` to replace and the words
        that replace it.
    """
    return {
        "foreign_image": (IMAGE, [FOREIGN_IMAGE]),
        "writable_stage": (f"{stage}:/e2e:ro", [f"{stage}:/e2e"]),
        "writable_volume": (f"{stage}/volume:/volume:ro", [f"{stage}/volume:/volume"]),
        "foreign_node_modules": (
            "-w",
            ["-v", "/srv/x/node_modules:/e2e/node_modules:ro", "-w"],
        ),
        "runtime_env": ("-w", ["-e", "NODE_OPTIONS=--require=/e2e/x.js", "-w"]),
        "off_host_proxy": (
            "-w",
            ["-e", "PLAYWRIGHT_PROXY=socks5://203.0.113.9:9050", "-w"],
        ),
        "entrypoint": ("-w", ["--entrypoint", "/bin/sh", "-w"]),
        "privileged": ("-w", ["--privileged", "-w"]),
        "other_cidfile": (f"--cidfile={run}/.cid", ["--cidfile=/srv/x/.cid"]),
        "no_log_driver": ("--log-driver=none", []),
        "reports_elsewhere": (f"{run}/reports:/reports", ["/srv/x:/reports"]),
    }


def bad_run(*replacements: tuple[str, str]) -> tuple[int, bool]:
    """Mask a run whose env file sets ``NODE_OPTIONS``, its command a probe.

    Args:
        *replacements: changes to the masker or its container check, for a
            negative control.

    Returns:
        The masker's exit code and whether the probe ran.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        marker = root / "ran"
        container, env = exec_tool(
            root, directory, [sys.executable, "-c", TOUCH, str(marker)]
        )
        (root / "stage" / ".env").write_text(
            f"{STAGE_ENV}{ENV_TRIGGERS['node_options']}\n", encoding="utf-8"
        )
        masker = [sys.executable, str(root / "bin" / MASKER.name), "mask"]
        result = subprocess.run(
            [*masker, str(directory), str(root / "reports"), "--", *container, "--"],
            capture_output=True,
            check=False,
            env=env,
        )
        return result.returncode, marker.exists()


class TestSpecSecretsContainer(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.module = load_from(self.root / "bin", self.root)
        self.run_dir = self.root / "run"

    def refused(self, argv: list[str]) -> bool:
        """Hold a container command against the check.

        Args:
            argv: the command through the image.

        Returns:
            Whether ``check_container`` refused it.
        """
        try:
            with without_docker_config():
                self.module.check_container(argv, self.run_dir)
        except self.module.spec_secrets.SpecSecretsError:
            return True
        return False

    def test_the_command_a_run_with_spec_secrets_starts_passes(self) -> None:
        self.assertFalse(self.refused(container_argv(self.root, self.run_dir)))

    def test_a_docker_config_the_caller_exports_stays_out_of_the_checks(self) -> None:
        argv = container_argv(self.root, self.run_dir)
        exported = {"DOCKER_CONFIG": str(open_config(self.root))}
        with unittest.mock.patch.dict(os.environ, exported):
            self.assertFalse(self.refused(argv))
            self.assertFalse(
                env_refused("PLAYWRIGHT_NETWORK_LEAK=false", keys=STAGE_KEYS)
            )

    def test_the_rendered_serial_and_queued_deploy_commands_pass(self) -> None:
        container_argv(self.root, self.run_dir)
        shared = self.root / "_shared"
        facts = {
            **ARGV_VARS,
            "_playwright_stage_dir": str(self.root / "stage"),
            "TEST_E2E_PLAYWRIGHT_SHARED_NODE_MODULES": f"{shared}/node_modules",
            "TEST_E2E_PLAYWRIGHT_SHARED_PERSONAS": f"{shared}/personas",
            "TEST_E2E_PLAYWRIGHT_IMAGE": IMAGE,
            "TEST_E2E_PLAYWRIGHT_MASK_ARGV": [],
            "_playwright_secrets_template_stat": {"stat": {"exists": True}},
            PATH_FACT: str(self.run_dir),
        }
        argv = render(run_argv(), **facts)
        container = argv[argv.index("docker") : argv.index(IMAGE) + 1]
        self.assertFalse(self.refused(container))
        self.assertFalse(self.refused([*container[:2], *QUEUED, *container[2:]]))

    def test_each_change_of_the_container_command_is_refused(self) -> None:
        stage = self.root / "stage"
        for name, (old, new) in argv_triggers(stage, self.run_dir).items():
            with self.subTest(trigger=name):
                argv = container_argv(self.root, self.run_dir)
                at = argv.index(old)
                argv[at : at + 1] = new
                self.assertTrue(self.refused(argv))

    def test_an_env_file_that_changes_what_the_container_runs_is_refused(
        self,
    ) -> None:
        for name, line in ENV_TRIGGERS.items():
            with self.subTest(trigger=name):
                argv = container_argv(self.root, self.run_dir)
                (self.root / "stage" / ".env").write_text(
                    f"{STAGE_ENV}{line}\n", encoding="utf-8"
                )
                self.assertTrue(self.refused(argv))

    def test_a_stage_dir_others_may_write_is_refused(self) -> None:
        argv = container_argv(self.root, self.run_dir)
        (self.root / "stage").chmod(0o775)
        self.assertTrue(self.refused(argv))

    def test_a_refused_container_never_runs(self) -> None:
        self.assertEqual(bad_run(), (70, False))

    def test_the_env_file_takes_only_fixed_and_declared_keys(self) -> None:
        self.assertFalse(env_refused("PLAYWRIGHT_NETWORK_LEAK=false", keys=STAGE_KEYS))
        self.assertFalse(
            env_refused("ADMIN_USERNAME=x", keys="APP_BASE_URL\nADMIN_USERNAME\n")
        )
        self.assertTrue(env_refused("FOO=bar", keys=STAGE_KEYS))
        self.assertTrue(
            env_refused("NODE_OPTIONS=--require=/e2e/x.js", keys="NODE_OPTIONS\n")
        )
        self.assertTrue(
            env_refused(
                "NODE_TLS_REJECT_UNAUTHORIZED=2", keys="NODE_TLS_REJECT_UNAUTHORIZED\n"
            )
        )
        self.assertTrue(env_refused("", keys=None))

    def test_the_deploy_lists_exactly_the_keys_the_env_template_declares(self) -> None:
        self.assertEqual(
            listed_keys(KEYS_SOURCE),
            (
                ["APP_BASE_URL", "ADMIN_USERNAME"],
                "{{ _playwright_stage_dir }}/.env.keys",
                [TEMPLATE_EXISTS],
            ),
        )


class TestSpecSecretsContainerNegativeControls(unittest.TestCase):
    def test_a_masker_that_leaves_the_container_part_unchecked_is_caught(
        self,
    ) -> None:
        self.assertEqual(bad_run(UNCHECKED), (0, True))

    def test_an_env_file_check_that_lets_an_undeclared_key_through_is_caught(
        self,
    ) -> None:
        self.assertFalse(env_refused("FOO=bar", UNDECLARED, keys=STAGE_KEYS))

    def test_a_check_that_sees_the_caller_docker_config_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module, run = load_from(root / "bin", root), root / "run"
            argv = container_argv(root, run)
            exported = {"DOCKER_CONFIG": str(open_config(root))}
            with (
                unittest.mock.patch.dict(os.environ, exported),
                self.assertRaises(module.spec_secrets.SpecSecretsError),
            ):
                module.check_container(argv, run)

    def test_a_secrets_run_that_mounts_the_stage_dir_writable_is_caught(
        self,
    ) -> None:
        for old in ("':/e2e' ~ (':ro' if", "'/volume:/volume' ~ (':ro' if"):
            with self.subTest(old=old):
                self.assertEqual(run_argv().count(old), 1)
                writable = run_argv().replace(old, old.replace("':ro'", "''"))
                self.assertIn(WRITABLE, mount_violations(writable))


if __name__ == "__main__":
    unittest.main()
