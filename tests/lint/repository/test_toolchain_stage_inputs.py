"""Lint: the root Dockerfile's toolchain stage reads only what it copies, and the published stage copies the tree on top.

The toolchain stage's ``COPY`` sources are the input set the local image tag
hashes and the local build sends as its context
(``utils/docker/image/toolchain.py``). A ``RUN`` of that stage that reads a
repository path outside the set builds from a file the tag does not cover, so
two checkouts sharing a tag could build different images.
"""

from __future__ import annotations

import re
import unittest
from pathlib import PurePosixPath

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.docker.image.toolchain import (
    DOCKERFILE,
    TOOLCHAIN_STAGE,
    copy_sources,
    input_files,
    stage_base,
    stages,
)
from utils.env.parser import parse_static_env

FINAL_STAGE = "full"
_LITERAL_PATH_RE = re.compile(r"\$\{INFINITO_SRC_DIR\}/([A-Za-z0-9_.][A-Za-z0-9_./-]*)")
_INDIRECT_PATH_RE = re.compile(
    r"\$\{INFINITO_SRC_DIR\}/\$\{(INFINITO_[A-Z0-9_]+)(?::\?)?\}"
)


def _covered(path: str, sources: list[str]) -> bool:
    candidate = PurePosixPath(path)
    return any(
        candidate == PurePosixPath(source) or PurePosixPath(source) in candidate.parents
        for source in sources
    )


def uncovered_reads(text: str, defaults: dict[str, str]) -> list[str]:
    """Return the repository paths a toolchain ``RUN`` reads outside the stage's ``COPY`` sources.

    Args:
        text: the Dockerfile's content.
        defaults: ``default.env`` values resolving ``${INFINITO_SRC_DIR}/${KEY}`` reads.
    """
    sources = copy_sources(text)
    offenders: list[str] = []
    for instruction in stages(text)[TOOLCHAIN_STAGE]:
        if instruction.keyword != "RUN":
            continue
        reads = [
            match.rstrip("/.") for match in _LITERAL_PATH_RE.findall(instruction.args)
        ]
        reads += [
            defaults.get(key, f"<unset {key}>")
            for key in _INDIRECT_PATH_RE.findall(instruction.args)
        ]
        offenders += [
            f"line {instruction.line}: {path}"
            for path in reads
            if not _covered(path, sources)
        ]
    return offenders


def whole_tree_copies(text: str, stage: str) -> list[int]:
    """Return the lines where the stage copies the whole build context.

    Args:
        text: the Dockerfile's content.
        stage: the stage to scan.
    """
    return [
        instruction.line
        for instruction in stages(text)[stage]
        if instruction.keyword in {"COPY", "ADD"}
        and instruction.args.split()[0] in {".", "./"}
    ]


NEGATIVE_DOCKERFILE = """ARG INFINITO_PARENT_IMAGE
FROM ${INFINITO_PARENT_IMAGE} AS toolchain
ARG INFINITO_SRC_DIR
COPY default.env ${INFINITO_SRC_DIR}/default.env
COPY scripts/install ${INFINITO_SRC_DIR}/scripts/install
RUN bash "${INFINITO_SRC_DIR}/scripts/install/venv.sh"; \\
  bash "${INFINITO_SRC_DIR}/scripts/outside/build.sh"; \\
  bash "${INFINITO_SRC_DIR}/${INFINITO_PROBE_INSTALL_SCRIPT:?}"
FROM toolchain AS full
COPY . ${INFINITO_SRC_DIR}
"""
WHOLE_TREE_TOOLCHAIN = NEGATIVE_DOCKERFILE.replace("FROM toolchain AS full\n", "")
PYTHON_INSTALL = "scripts/install/python.sh"
COMPAT = "PIP_CONFIG_SETTINGS=editable_mode=compat"


def strict_editable_installs(text: str) -> list[int]:
    """Args:
        text: the Dockerfile's content.

    Returns:
        The lines of each toolchain ``RUN`` that calls ``python.sh`` without
        ``PIP_CONFIG_SETTINGS=editable_mode=compat``.
    """
    return [
        instruction.line
        for instruction in stages(text)[TOOLCHAIN_STAGE]
        if instruction.keyword == "RUN"
        and PYTHON_INSTALL in instruction.args
        and COMPAT not in instruction.args
    ]


class TestToolchainStageInputs(unittest.TestCase):
    def setUp(self) -> None:
        self.text = read_text(str(PROJECT_ROOT / DOCKERFILE))
        self.defaults = parse_static_env(PROJECT_ROOT / "default.env")

    def test_every_repository_path_a_toolchain_run_reads_is_copied(self) -> None:
        self.assertEqual(uncovered_reads(self.text, self.defaults), [])

    def test_the_toolchain_stage_never_copies_the_whole_tree(self) -> None:
        self.assertEqual(whole_tree_copies(self.text, TOOLCHAIN_STAGE), [])

    def test_the_final_stage_copies_the_tree_on_top_of_the_toolchain_stage(
        self,
    ) -> None:
        self.assertEqual(list(stages(self.text))[-1], FINAL_STAGE)
        self.assertEqual(stage_base(self.text, FINAL_STAGE), TOOLCHAIN_STAGE)
        self.assertNotEqual(whole_tree_copies(self.text, FINAL_STAGE), [])

    def test_the_hashed_files_are_exactly_the_files_below_the_copy_sources(
        self,
    ) -> None:
        sources = copy_sources(self.text)
        files = input_files(PROJECT_ROOT)
        self.assertTrue(all(_covered(rel, sources) for rel in files))
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(any(_covered(rel, [source]) for rel in files))

    def test_the_toolchain_installs_the_package_in_compat_editable_mode(self) -> None:
        self.assertTrue(
            any(
                PYTHON_INSTALL in instruction.args
                for instruction in stages(self.text)[TOOLCHAIN_STAGE]
            )
        )
        self.assertEqual(strict_editable_installs(self.text), [])

    def test_negative_control_a_strict_editable_install_is_flagged(self) -> None:
        planted = self.text.replace(COMPAT + " ", "")
        self.assertNotEqual(planted, self.text)
        self.assertNotEqual(strict_editable_installs(planted), [])

    def test_negative_control_an_uncopied_read_and_a_whole_tree_copy_are_flagged(
        self,
    ) -> None:
        offenders = uncovered_reads(
            NEGATIVE_DOCKERFILE,
            {"INFINITO_PROBE_INSTALL_SCRIPT": "roles/probe/files/install.sh"},
        )
        self.assertEqual(
            offenders,
            [
                "line 6: scripts/outside/build.sh",
                "line 6: roles/probe/files/install.sh",
            ],
        )
        self.assertEqual(whole_tree_copies(NEGATIVE_DOCKERFILE, TOOLCHAIN_STAGE), [])
        self.assertEqual(whole_tree_copies(WHOLE_TREE_TOOLCHAIN, TOOLCHAIN_STAGE), [9])
        self.assertEqual(uncovered_reads(WHOLE_TREE_TOOLCHAIN, {}), [])


if __name__ == "__main__":
    unittest.main()
