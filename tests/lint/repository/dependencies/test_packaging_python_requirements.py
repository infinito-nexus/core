#!/usr/bin/env python3

from __future__ import annotations

import re
import shlex
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_SPEC_IF = re.compile(r"^%if\s+0%\{\?(?P<macro>\w+)\}\s*==\s*(?P<value>\d+)$")


def control_paragraphs(text: str) -> list[dict[str, str]]:
    """Args:
        text: a Debian control file.

    Returns:
        Its paragraphs as field mappings, continuation lines folded in.
    """
    paragraphs: list[dict[str, str]] = [{}]
    field = ""
    for line in text.splitlines():
        if not line.strip():
            paragraphs.append({})
        elif line[0].isspace():
            paragraphs[-1][field] += f"\n{line.strip()}"
        else:
            field, _, value = line.partition(":")
            paragraphs[-1][field] = value.strip()
    return [paragraph for paragraph in paragraphs if paragraph]


def control_depends(text: str, package: str) -> list[list[str]]:
    """Args:
        text: a Debian control file.
        package: the binary package whose ``Depends`` are read.

    Returns:
        One list of alternatives per relation.
    """
    binary = next(
        paragraph
        for paragraph in control_paragraphs(text)
        if paragraph.get("Package") == package
    )
    return [
        [" ".join(alternative.split()) for alternative in relation.split("|")]
        for relation in binary["Depends"].split(",")
        if relation.strip()
    ]


def pkgbuild_array(text: str, name: str) -> list[str]:
    """Args:
        text: a PKGBUILD.
        name: the array variable to read.

    Returns:
        The words of the array, quotes removed.
    """
    match = re.search(rf"^{name}=\((?P<body>.*?)\)", text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"the PKGBUILD declares no {name} array")
    return shlex.split(match.group("body"), comments=True)


def spec_requires(text: str, macros: dict[str, int]) -> list[str]:
    """Args:
        text: an RPM spec.
        macros: the numeric macros of the build; an absent one expands empty.

    Returns:
        The ``Requires`` that hold under those macros.
    """
    requires: list[str] = []
    active = [True]
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("%if"):
            match = _SPEC_IF.match(stripped)
            if match is None:
                raise AssertionError(f"unsupported spec conditional: {stripped}")
            holds = int(f"0{macros.get(match['macro'], '')}") == int(match["value"])
            active.append(active[-1] and holds)
        elif stripped == "%else":
            active[-1] = active[-2] and not active[-1]
        elif stripped == "%endif":
            active.pop()
        elif active[-1] and stripped.startswith("Requires:"):
            requires.append(" ".join(stripped.removeprefix("Requires:").split()))
    return requires


class TestPackagingPythonRequirements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = PROJECT_ROOT
        cls.arch_pkgbuild = cls.repo_root / "packaging" / "arch" / "PKGBUILD"
        cls.fedora_spec = cls.repo_root / "packaging" / "fedora" / "infinito-nexus.spec"
        cls.debian_control = cls.repo_root / "packaging" / "debian" / "control"

    def test_fedora_spec_relaxes_python_capability_on_el9_only(self):  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        spec_text = read_text(str(self.fedora_spec))
        el9 = spec_requires(spec_text, {"rhel": 9})
        self.assertIn("python3", el9)
        self.assertNotIn("python3 >= 3.11", el9)
        for macros in ({"rhel": 10}, {}):
            with self.subTest(macros=macros):
                requires = spec_requires(spec_text, macros)
                self.assertIn("python3 >= 3.11", requires)
                self.assertNotIn("python3", requires)

    def test_debian_control_keeps_explicit_python_311_floor(self):  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        depends = control_depends(read_text(str(self.debian_control)), "infinito-nexus")
        self.assertIn(["python3 (>= 3.11)"], depends)

    def test_arch_pkgbuild_requires_docker_compose(self):  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        depends = pkgbuild_array(read_text(str(self.arch_pkgbuild)), "depends")
        self.assertIn("docker-compose", depends)

    def test_debian_control_requires_compose_v2_plugin(self):  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        depends = control_depends(read_text(str(self.debian_control)), "infinito-nexus")
        self.assertIn(["docker-compose-v2", "docker-compose-plugin"], depends)
        self.assertNotIn(
            "docker-compose",
            {
                alternative.split(maxsplit=1)[0]
                for relation in depends
                for alternative in relation
            },
        )

    def test_fedora_spec_requires_compose_plugin(self):  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        spec_text = read_text(str(self.fedora_spec))
        for macros in ({"rhel": 9}, {"rhel": 10}, {}):
            with self.subTest(macros=macros):
                self.assertIn("docker-compose-plugin", spec_requires(spec_text, macros))


if __name__ == "__main__":
    unittest.main()
