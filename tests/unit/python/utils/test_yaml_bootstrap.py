"""The stdlib block reader agrees with PyYAML on its subset and rejects the rest."""

from __future__ import annotations

import unittest

import yaml

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_str
from utils.distros import FILE_META_DISTROS
from utils.yaml_bootstrap import BootstrapYamlError, load_block

IN_SUBSET = (
    "a: b\n",
    "a:\n  b: c\n  d: e\n",
    'b: "c:d"\n',
    "x: quay.io/centos/centos:latest\n",
    "a:\n  - one\n  - two\n",
    "# leading comment\na: b # trailing comment\n",
    "---\na: b\n",
    'tpl: "example.test/{owner}/{slug}:{tag}"\n',
    "a:\n  b:\n    - x\nc: d\n",
)

OUT_OF_SUBSET = (
    "a: 1\n",
    "a: true\n",
    "a: null\n",
    "a: [1, 2]\n",
    "a: {b: c}\n",
    "a: &anchor v\n",
    "a: |\n  block\n",
    "a: 'single'\n",
    "a:\nb: v\n",
    "a: b\na: c\n",
    "a:\n\tb: c\n",
    "a: b\n---\nc: d\n",
    "a:\n  - one\n   - two\n",
)


_UNPARSEABLE = object()

TOKENS = (
    "1",
    "1_000",
    "0x10",
    "0o17",
    ".5",
    "-1",
    "+1",
    "1e3",
    ".inf",
    ".nan",
    "12:30",
    "2021-01-01",
    "true",
    "True",
    "On",
    "off",
    "y",
    "n",
    "null",
    "~",
    "b",
    "b c",
    "b:c",
    "b: c",
    "b#c",
    "b #c",
    '"b"',
    '"b: c"',
    "'b'",
    "[1]",
    "{a: b}",
    "&x v",
    "*x",
    "!!str v",
    "a/b",
    "quay.io/c/c:latest",
    "-b",
    "%y",
    "@x",
    ">-",
    "|",
    "",
)

TEMPLATES = (
    "k: {t}\n",
    "{t}: v\n",
    "k:\n  - {t}\n",
    "k:\n  {t}: v\n",
    "k:\n  - {t}\n  - z\n",
)

STRUCTURES = (
    "",
    "\n",
    "# only a comment\n",
    "---\n",
    "matrix:\n  - name: arch\n  - name: debian\n",
    "a:\n- x\n- y\n",
    "- a\n- b\n",
    "plain\n",
    "a: b\nc:\n  d: e\n",
    "a:\n  b: c\n d: e\n",
    "a: b\n\n\nc: d\n",
    'a: "b" trailing\n',
    'a: "b\\nc"\n',
    "a:  b  \n",
    "a : b\n",
    "a: see this: here\n",
    "a:b\n",
    "a: # note\n",
)


class TestNoSilentDivergence(unittest.TestCase):
    """Every accepted document parses exactly as PyYAML parses it."""

    def test_reader_equals_pyyaml_or_raises(self) -> None:
        documents = [tpl.format(t=token) for tpl in TEMPLATES for token in TOKENS]
        documents.extend(STRUCTURES)
        accepted = 0
        for document in documents:
            with self.subTest(document=document):
                try:
                    expected = load_yaml_str(document)
                except yaml.YAMLError:
                    expected = _UNPARSEABLE
                try:
                    parsed = load_block(document)
                except BootstrapYamlError:
                    continue
                accepted += 1
                self.assertEqual(parsed, expected)
        self.assertGreater(accepted, 0)


class TestSpotStaysInSubset(unittest.TestCase):
    def test_reader_matches_pyyaml_on_the_distro_spot(self) -> None:
        path = str(PROJECT_ROOT / FILE_META_DISTROS)
        parsed = load_block(read_text(path))
        expected = load_yaml(path)
        self.assertEqual(parsed, expected)
        self.assertEqual(list(parsed["distros"]), list(expected["distros"]))


class TestSupportedSubset(unittest.TestCase):
    def test_reader_matches_pyyaml(self) -> None:
        for snippet in IN_SUBSET:
            with self.subTest(snippet=snippet):
                self.assertEqual(load_block(snippet), load_yaml_str(snippet))


class TestRejectedConstructs(unittest.TestCase):
    def test_out_of_subset_fails_loud(self) -> None:
        for snippet in OUT_OF_SUBSET:
            with self.subTest(snippet=snippet), self.assertRaises(BootstrapYamlError):
                load_block(snippet)


if __name__ == "__main__":
    unittest.main()
