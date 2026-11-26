"""The runner image installs the OpenTofu, age and KeePassXC of the node that builds it.

The deploy matrix schedules the role on every architecture of its rotation
unless ``meta/services.yml`` narrows it, and the stack host builds the runner
image natively. A pin for one architecture only therefore ships a binary the
other architecture cannot execute, which ``build.sh install`` meets as
``Exec format error``.
"""

from __future__ import annotations

import copy
import re
import shlex
import unittest

from ansible.errors import AnsibleError

from utils.cache.files import read_text
from utils.github.variant.pools import ARCHITECTURES
from utils.roles.meta_lookup import get_role_architectures

from ._fake_opentofu_build import Build
from .test_runner_build import (
    BUILD,
    DOCKERFILE,
    HOST_ARCHITECTURE_BY_KERNEL,
    OLD,
    ROLE,
    RUNNER,
    resolve,
)

TOOLS = {
    "opentofu": {
        "arg": "SEMAPHORE_OPENTOFU",
        "asset": {"amd64": "_linux_amd64.tar.gz", "arm64": "_linux_arm64.tar.gz"},
    },
    "age": {
        "arg": "SEMAPHORE_AGE",
        "asset": {"amd64": "-linux-amd64.tar.gz", "arm64": "-linux-arm64.tar.gz"},
    },
    "keepassxc": {
        "arg": "SEMAPHORE_KEEPASSXC",
        "asset": {"amd64": "-x86_64.AppImage", "arm64": "-aarch64.AppImage"},
    },
}
MACHINES = {arch: kernel for kernel, arch in HOST_ARCHITECTURE_BY_KERNEL.items()}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SOURCE = "${INFINITO_SRC_DIR}"


def stage_instructions(dockerfile: str, stage: str) -> list[tuple[str, str]]:
    """
    Args:
        dockerfile: the runner Dockerfile.
        stage: the name its ``FROM ... AS`` line gives the stage.

    Returns:
        ``(instruction, arguments)`` of every instruction of that stage, with
        line continuations joined.
    """
    stages: dict[str | None, list[tuple[str, str]]] = {}
    current = None
    for line in dockerfile.replace("\\\n", " ").splitlines():
        keyword, _, arguments = line.strip().partition(" ")
        if keyword == "FROM":
            current = arguments.rpartition(" AS ")[2] if " AS " in arguments else None
        elif keyword:
            stages.setdefault(current, []).append((keyword, arguments.strip()))
    return stages[stage]


def scheduled_architectures() -> tuple[str, ...]:
    """Returns:
    Every architecture the deploy matrix may schedule the role on.
    """
    declared = get_role_architectures(ROLE)
    return tuple(arch for arch in ARCHITECTURES if not declared or arch in declared)


def pin_findings(runner: dict, architectures: tuple[str, ...]) -> list[str]:
    """Args:
        runner: the ``task-runner`` entity of ``meta/services.yml``.
        architectures: the architectures the role is scheduled on.

    Returns:
        One finding per tool and architecture whose download is missing, is
        not that architecture's release asset, carries no sha256, or shares
        its sum with another architecture; and one per pinned sum no
        ``update:`` entry moves along with the version.
    """
    findings = []
    moved = {
        (source.get("checksum_key"), source.get("checksum_url"))
        for source in runner.get("update", [])
    }
    for tool, spec in TOOLS.items():
        sums = {}
        for arch in architectures:
            url = runner.get(f"{tool}_url_{arch}")
            digest = runner.get(f"{tool}_sha256_{arch}")
            if not url or not str(url).endswith(spec["asset"][arch]):
                findings.append(f"{tool}: {arch} downloads {url!r}")
            if not digest or not SHA256.match(str(digest)):
                findings.append(f"{tool}: {arch} pins no sha256")
            elif digest in sums.values():
                findings.append(
                    f"{tool}: {arch} reuses the sum of another architecture"
                )
            sums[arch] = digest
            if (f"{tool}_sha256_{arch}", url) not in moved:
                findings.append(f"{tool}: no update entry moves the {arch} sum")
    return findings


class TestPins(unittest.TestCase):
    def test_the_matrix_schedules_the_role_on_both_architectures(self) -> None:
        self.assertEqual(scheduled_architectures(), ARCHITECTURES)

    def test_every_scheduled_architecture_has_its_own_pins(self) -> None:
        self.assertEqual(pin_findings(RUNNER, scheduled_architectures()), [])

    def test_the_provider_locks_cover_every_scheduled_platform(self) -> None:
        self.assertEqual(
            sorted(RUNNER["opentofu_platforms"]),
            sorted(f"linux_{arch}" for arch in scheduled_architectures()),
        )

    def test_negative_control_amd64_only_pins_are_reported(self) -> None:
        planted = copy.deepcopy(RUNNER)
        for tool in TOOLS:
            planted[f"{tool}_url_arm64"] = planted[f"{tool}_url_amd64"]
            planted[f"{tool}_sha256_arm64"] = planted[f"{tool}_sha256_amd64"]
        findings = pin_findings(planted, scheduled_architectures())
        for tool in TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(
                    f"{tool}: arm64 reuses the sum of another architecture", findings
                )
                self.assertTrue(
                    any(f.startswith(f"{tool}: arm64 downloads") for f in findings)
                )

    def test_negative_control_a_sum_the_updater_does_not_move_is_reported(self) -> None:
        planted = copy.deepcopy(RUNNER)
        planted["update"] = [
            source
            for source in planted["update"]
            if source.get("checksum_key") != "age_sha256_arm64"
        ]
        self.assertEqual(
            pin_findings(planted, scheduled_architectures()),
            ["age: no update entry moves the arm64 sum"],
        )


class TestBuildArguments(unittest.TestCase):
    def test_each_build_host_gets_the_binaries_of_its_architecture(self) -> None:
        for arch in ARCHITECTURES:
            with self.subTest(arch=arch):
                args = resolve(primary=[ROLE], tag=OLD, machine=MACHINES[arch])[
                    "SEMAPHORE_RUNNER_BUILD_ARGS"
                ]
                for tool, spec in TOOLS.items():
                    version = RUNNER[f"{tool}_version"]
                    self.assertEqual(
                        args[f"{spec['arg']}_URL"],
                        RUNNER[f"{tool}_url_{arch}"].replace("{version}", version),
                    )
                    self.assertTrue(
                        args[f"{spec['arg']}_URL"].endswith(spec["asset"][arch])
                    )
                    self.assertEqual(
                        args[f"{spec['arg']}_SHA256"], RUNNER[f"{tool}_sha256_{arch}"]
                    )
                self.assertEqual(args["SEMAPHORE_OPENTOFU_PLATFORM"], f"linux_{arch}")

    def test_an_image_built_on_one_architecture_is_rebuilt_on_the_other(self) -> None:
        digests = {
            resolve(primary=[ROLE], tag=OLD, machine=MACHINES[arch])[
                "SEMAPHORE_RUNNER_INPUTS_DIGEST"
            ]
            for arch in ARCHITECTURES
        }
        self.assertEqual(len(digests), len(ARCHITECTURES))

    def test_negative_control_an_unmapped_build_host_fails_the_build_arguments(
        self,
    ) -> None:
        with self.assertRaises(AnsibleError):
            resolve(primary=[ROLE], tag=OLD, machine="riscv64")


class TestMirrorPlatform(unittest.TestCase):
    def setUp(self) -> None:
        self.build = Build(RUNNER["opentofu_version"])
        self.addCleanup(self.build.close)

    def test_the_dockerfile_mirrors_the_platform_of_the_build_arguments(self) -> None:
        stage = stage_instructions(read_text(str(DOCKERFILE)), "opentofu")
        self.assertIn(("ARG", "SEMAPHORE_OPENTOFU_PLATFORM"), stage)
        steps = [
            shlex.split(step)
            for keyword, arguments in stage
            if keyword == "RUN"
            for step in arguments.split("&&")
        ]
        self.assertIn(
            [
                "bash",
                f"{SOURCE}/roles/web-app-semaphore/files/shell/opentofu/build.sh",
                "mirror",
                f"{SOURCE}/roles/web-app-semaphore/files/opentofu",
                "${SEMAPHORE_OPENTOFU_PLATFORM}",
            ],
            steps,
        )

    def test_the_mirror_fetches_the_providers_of_the_given_platform(self) -> None:
        for arch in ARCHITECTURES:
            with self.subTest(arch=arch):
                result = self.build.run(
                    "mirror", str(self.build.opentofu), f"linux_{arch}"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                mirrors = [
                    call["argv"]
                    for call in self.build.calls()
                    if call["argv"][:2] == ["providers", "mirror"]
                ]
                self.assertTrue(mirrors)
                for argv in mirrors:
                    self.assertIn(f"-platform=linux_{arch}", argv)
                    self.assertFalse(
                        any(
                            a.startswith("-platform=")
                            and a != f"-platform=linux_{arch}"
                            for a in argv
                        )
                    )

    def test_negative_control_a_mirror_without_a_platform_is_refused(self) -> None:
        for platform in ((), ("",), ("amd64",)):
            with self.subTest(platform=platform):
                result = self.build.run("mirror", str(self.build.opentofu), *platform)
                self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn('PLATFORM="linux_amd64"', read_text(str(BUILD)))


if __name__ == "__main__":
    unittest.main()
