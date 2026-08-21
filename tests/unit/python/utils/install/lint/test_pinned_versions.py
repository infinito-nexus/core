"""The GitHub-release installers read their release from the sys-lint pins.

Resolving the latest tag at install time made `make install-lint` die on a DNS
hiccup (`URLError: Temporary failure in name resolution`) and left the
installed version unreproducible across runs of the same commit. Repository
and version now come from ``roles/sys-lint/meta/services.yml``, the same shape
the ``update-repository-refs`` CI job bumps.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.install.lint import actionlint, hadolint, shfmt
from utils.install.lint.pinned import _parse_pins, pinned_release, resolve_release
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_INSTALLERS = (
    (actionlint, "actionlint", "ACTIONLINT_VERSION"),
    (hadolint, "hadolint", "HADOLINT_VERSION"),
    (shfmt, "shfmt", "SHFMT_VERSION"),
)

_PINS = PROJECT_ROOT / "roles" / "sys-lint" / ROLE_FILE_META_SERVICES

_BOOTSTRAP_PROBE = """
import sys


class _NoPyYAML:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "yaml" or fullname.startswith("yaml."):
            raise ImportError("PyYAML is absent during the lint bootstrap")
        return None


sys.meta_path.insert(0, _NoPyYAML())

from utils.install.lint import actionlint, hadolint, shfmt

for module, tool in ((actionlint, "actionlint"), (hadolint, "hadolint"), (shfmt, "shfmt")):
    print(tool, *module.resolve_release(tool))
"""


class TestPinnedRelease(unittest.TestCase):
    def _pin(self, root: Path, body: str) -> None:
        meta = root / "sys-lint" / "meta"
        meta.mkdir(parents=True)
        (meta / "services.yml").write_text(body, encoding="utf-8")

    def test_reads_the_slug_and_strips_the_v(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._pin(
                root,
                "actionlint:\n"
                "  repository: https://github.com/rhysd/actionlint.git\n"
                "  ref: v1.7.12\n",
            )
            self.assertEqual(
                pinned_release("actionlint", root), ("rhysd/actionlint", "1.7.12")
            )

    def test_a_missing_pin_raises_instead_of_guessing(self) -> None:
        with TemporaryDirectory() as tmp, self.assertRaises(RuntimeError):
            pinned_release("actionlint", Path(tmp))

    def test_a_pin_without_a_ref_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._pin(
                root,
                "shfmt:\n  repository: https://github.com/mvdan/sh.git\n",
            )
            with self.assertRaises(RuntimeError):
                pinned_release("shfmt", root)


class TestResolveRelease(unittest.TestCase):
    def test_every_tool_resolves_without_the_network(self) -> None:
        for _module, tool, _env in _INSTALLERS:
            with (
                self.subTest(tool=tool),
                mock.patch.dict("os.environ", {}, clear=True),
            ):
                self.assertEqual(resolve_release(tool), pinned_release(tool))

    def test_an_explicit_version_overrides_the_pin(self) -> None:
        for _module, tool, env in _INSTALLERS:
            with (
                self.subTest(tool=tool),
                mock.patch.dict("os.environ", {env: "v9.9.9"}),
            ):
                slug, version = resolve_release(tool)
                self.assertEqual(version, "9.9.9")
                self.assertEqual(slug, pinned_release(tool)[0])


class TestInstallersUseThePins(unittest.TestCase):
    def test_every_installer_uses_the_shared_resolver(self) -> None:
        for module, tool, _env in _INSTALLERS:
            with self.subTest(tool=tool):
                self.assertIs(module.resolve_release, resolve_release)

    def test_no_installer_still_imports_the_latest_tag_resolver(self) -> None:
        for module, tool, _env in _INSTALLERS:
            with self.subTest(tool=tool):
                self.assertFalse(hasattr(module, "resolve_latest_tag"))
                self.assertFalse(hasattr(module, "_LATEST_URL"))


class TestBootstrapNeedsNoPyYAML(unittest.TestCase):
    """Every ``lint-*`` target depends on ``install-lint``, which runs before
    the Python dependencies exist. Importing PyYAML from the pin reader broke
    the whole lint stage with ``ModuleNotFoundError: No module named 'yaml'``.
    """

    def test_the_installers_import_and_resolve_without_pyyaml(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", _BOOTSTRAP_PROBE],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for _module, tool, _env in _INSTALLERS:
            self.assertIn(tool, result.stdout)

    def test_the_hand_parser_agrees_with_pyyaml(self) -> None:
        self.assertEqual(_parse_pins(read_text(str(_PINS))), load_yaml_any(str(_PINS)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
