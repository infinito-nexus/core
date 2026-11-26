"""Lint: every privileged systemd container of the DiD, swarm and infra stacks
masks systemd-sysctl.service.

A privileged container mounts /proc/sys read-write, so the systemd-sysctl it
boots applies the image's vendor sysctl.d files to the host kernel, among them
Debian's `kernel.core_pattern=core`. The infinito image masks the unit in the
root Dockerfile, the swarm node and the infra runner inherit it from that
image, and the target image masks it in its init script."""

import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import dockerfile_commands, dockerfile_instructions, shell_commands

UNIT = "systemd-sysctl.service"
MASKERS = {
    "Dockerfile": dockerfile_commands,
    "compose/target/init.sh": shell_commands,
}
INHERITOR = "compose/swarm/Dockerfile"
INFINITO_IMAGE = "${INFINITO_IMAGE}"
COMPOSE_FILES = (
    "compose.yml",
    "compose/swarm/compose.yml",
    "compose/infra.yml",
)
MASKED_BUILD_CONTEXTS = {".", "compose/target"}


def _masks(commands):
    """Args:
        commands: the argv of every command an image build or init runs.

    Returns:
        Whether one of the commands is a ``systemctl mask`` of systemd-sysctl.
    """
    return any(
        argv[:2] == ["systemctl", "mask"] and UNIT in argv[2:] for argv in commands
    )


def _base_image(text):
    """Args:
        text: a Dockerfile.

    Returns:
        The image its final build stage starts from.
    """
    stages = [
        args for keyword, args in dockerfile_instructions(text) if keyword == "FROM"
    ]
    return stages[-1].split(maxsplit=1)[0] if stages else None


def _unmasked_privileged(services):
    offenders = []
    for name, service in (services or {}).items():
        if not isinstance(service, dict) or not service.get("privileged"):
            continue
        build = service.get("build")
        context = build.get("context") if isinstance(build, dict) else build
        image = str(service.get("image", ""))
        if context in MASKED_BUILD_CONTEXTS or image.startswith("${INFINITO_IMAGE"):
            continue
        offenders.append(name)
    return offenders


class TestContainerSysctlMasked(unittest.TestCase):
    def test_images_mask_systemd_sysctl(self):  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        for path, commands in MASKERS.items():
            with self.subTest(path=path):
                self.assertTrue(_masks(commands(read_text(str(PROJECT_ROOT / path)))))

    def test_derived_images_inherit_the_mask(self):
        self.assertEqual(
            _base_image(read_text(str(PROJECT_ROOT / INHERITOR))), INFINITO_IMAGE
        )

    def test_every_privileged_service_runs_a_masked_image(self):
        for path in COMPOSE_FILES:
            services = load_yaml_any(str(PROJECT_ROOT / path)).get("services", {})
            with self.subTest(path=path):
                self.assertTrue(any(s.get("privileged") for s in services.values()))
                self.assertEqual(_unmasked_privileged(services), [])

    def test_negative_control_a_dropped_mask_is_flagged(self):
        self.assertFalse(
            _masks(
                dockerfile_commands(
                    "RUN systemctl mask getty.target \\\n    tmp.mount\n"
                )
            )
        )
        self.assertTrue(
            _masks(
                dockerfile_commands(
                    "RUN systemctl mask getty.target \\\n    systemd-sysctl.service\n"
                )
            )
        )
        self.assertFalse(
            _masks(
                dockerfile_commands("RUN systemctl unmask systemd-sysctl.service.d\n")
            )
        )
        self.assertFalse(
            _masks(shell_commands("# systemctl mask systemd-sysctl.service\n"))
        )

    def test_negative_control_a_foreign_base_image_is_flagged(self):
        self.assertNotEqual(
            _base_image(f"FROM {INFINITO_IMAGE} AS build\nFROM debian:13\n"),
            INFINITO_IMAGE,
        )

    def test_negative_control_a_foreign_privileged_image_is_flagged(self):
        services = {"rogue": {"privileged": True, "image": "debian:13"}}
        self.assertEqual(_unmasked_privileged(services), ["rogue"])


if __name__ == "__main__":
    unittest.main()
