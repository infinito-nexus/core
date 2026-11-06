from __future__ import annotations

import os
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.install import codex as codex_mod
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_PIN = (
    "codex:\n"
    "  npm_version: 0.166.0\n"
    "  update:\n"
    "    key: npm_version\n"
    "    type: npm\n"
    '    package: "@openai/codex"\n'
)


def _repo(root: Path, role: str, body: str) -> Path:
    services = root / "roles" / role / ROLE_FILE_META_SERVICES
    services.parent.mkdir(parents=True)
    services.write_text(body, encoding="utf-8")
    return root


def _program(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)


class _Scratch(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)


class TestPinnedPackage(_Scratch):
    def _pin(self, role: str, body: str) -> tuple[str, str]:
        return codex_mod.pinned_package(_repo(self.root, role, body))

    def test_the_role_pin_resolves_through_the_update_source(self) -> None:
        services = PROJECT_ROOT / "roles" / codex_mod.ROLE / ROLE_FILE_META_SERVICES
        entity = load_yaml(str(services))[codex_mod.ENTITY]
        self.assertEqual(
            codex_mod.pinned_package(PROJECT_ROOT),
            (entity["update"]["package"], str(entity[entity["update"]["key"]])),
        )

    def test_the_version_is_read_from_the_key_the_source_names(self) -> None:
        body = (
            "codex:\n"
            "  npm_version: 0.0.1\n"
            "  release: 1.2.3\n"
            "  update:\n"
            "    key: release\n"
            "    type: npm\n"
            '    package: "@scope/client"\n'
        )
        self.assertEqual(self._pin(codex_mod.ROLE, body), ("@scope/client", "1.2.3"))

    def test_a_source_without_a_key_pins_the_version_key(self) -> None:
        body = (
            "codex:\n  version: 2.0.0\n  update:\n    type: npm\n    package: client\n"
        )
        self.assertEqual(self._pin(codex_mod.ROLE, body), ("client", "2.0.0"))

    def test_the_npm_source_is_picked_among_several(self) -> None:
        body = (
            "codex:\n"
            "  webui: v1.0.0\n"
            "  npm_version: 0.4.0\n"
            "  update:\n"
            "    - key: webui\n"
            "      type: git_tags\n"
            "      package: webui\n"
            "    - key: npm_version\n"
            "      type: npm\n"
            "      package: client\n"
        )
        self.assertEqual(self._pin(codex_mod.ROLE, body), ("client", "0.4.0"))

    def test_a_missing_role_is_a_pin_error(self) -> None:
        with self.assertRaises(codex_mod.CodexPinError):
            self._pin("dsk-gnt-other", _PIN)

    def test_a_missing_entity_is_a_pin_error(self) -> None:
        with self.assertRaises(codex_mod.CodexPinError):
            self._pin(codex_mod.ROLE, _PIN.replace("codex:", "other:"))

    def test_an_entity_without_an_npm_source_is_a_pin_error(self) -> None:
        body = "codex:\n  version: 1.0.0\n  update:\n    type: git_tags\n"
        with self.assertRaises(codex_mod.CodexPinError):
            self._pin(codex_mod.ROLE, body)

    def test_a_source_without_a_package_is_a_pin_error(self) -> None:
        body = "codex:\n  version: 1.0.0\n  update:\n    type: npm\n"
        with self.assertRaises(codex_mod.CodexPinError):
            self._pin(codex_mod.ROLE, body)

    def test_a_key_without_a_version_is_a_pin_error(self) -> None:
        body = "codex:\n  update:\n    key: npm_version\n    type: npm\n    package: client\n"
        with self.assertRaises(codex_mod.CodexPinError):
            self._pin(codex_mod.ROLE, body)


class TestInstalledVersion(_Scratch):
    def setUp(self) -> None:
        super().setUp()
        self.caller_home = self.root / "caller-home"
        self.caller_home.mkdir()
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{os.environ['PATH']}"
        os.environ["CODEX_HOME"] = str(self.caller_home)

    def test_reports_the_version_codex_prints(self) -> None:
        _program(
            self.bin, "codex", 'touch "$CODEX_HOME/aliases"\necho "codex-cli 9.8.7"\n'
        )
        self.assertEqual(codex_mod.installed_version(), "9.8.7")
        self.assertEqual(list(self.caller_home.iterdir()), [])

    def test_no_codex_on_path_reports_nothing(self) -> None:
        os.environ["PATH"] = str(self.bin)
        self.assertEqual(codex_mod.installed_version(), "")

    def test_a_failing_probe_reports_nothing(self) -> None:
        _program(self.bin, "codex", "echo 'codex-cli 9.8.7'\nexit 1\n")
        self.assertEqual(codex_mod.installed_version(), "")

    def test_a_hanging_probe_reports_nothing(self) -> None:
        _program(self.bin, "codex", "sleep 3\necho 'codex-cli 9.8.7'\n")
        with mock.patch.object(codex_mod, "PROBE_TIMEOUT_SECONDS", 0.2):
            self.assertEqual(codex_mod.installed_version(), "")


class TestEnsurePublished(_Scratch):
    def setUp(self) -> None:
        super().setUp()
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{os.environ['PATH']}"

    def _check(self) -> str:
        with self.assertRaises(codex_mod.CodexInstallError) as caught:
            codex_mod.ensure_published("client", "1.0.0")
        return str(caught.exception)

    def test_a_published_pin_passes(self) -> None:
        _program(
            self.bin,
            "npm",
            '[ "$*" = "view client@1.0.0 version" ] || exit 9\necho 1.0.0\n',
        )
        codex_mod.ensure_published("client", "1.0.0")

    def test_an_unreachable_registry_names_the_network_cause(self) -> None:
        _program(self.bin, "npm", "echo 'npm error code ENOTFOUND' >&2\nexit 1\n")
        message = self._check()
        self.assertIn("cannot resolve client@1.0.0 through its registry", message)
        self.assertIn("ENOTFOUND", message)

    def test_a_silent_registry_names_the_network_cause(self) -> None:
        _program(self.bin, "npm", "sleep 3\necho 1.0.0\n")
        with mock.patch.object(codex_mod, "PROBE_TIMEOUT_SECONDS", 0.2):
            message = self._check()
        self.assertIn("cannot reach its registry", message)

    def test_a_version_missing_upstream_is_refused(self) -> None:
        _program(self.bin, "npm", "exit 0\n")
        self.assertIn("client@1.0.0 is not published", self._check())


class TestEnsureCodexPresent(_Scratch):
    def setUp(self) -> None:
        super().setUp()
        self.repo = _repo(self.root, codex_mod.ROLE, _PIN)
        for name in ("ensure_npm_present", "ensure_published"):
            patcher = mock.patch.object(codex_mod, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def _ensure(self, *reported: str) -> mock.MagicMock:
        with (
            mock.patch.object(
                codex_mod, "installed_version", side_effect=list(reported)
            ),
            mock.patch.object(codex_mod, "npm_install_global") as install,
        ):
            codex_mod.ensure_codex_present(self.repo)
        return install

    def test_a_client_at_the_pin_is_left_alone(self) -> None:
        self._ensure("0.166.0").assert_not_called()
        self.ensure_published.assert_not_called()

    def test_a_missing_client_is_installed_at_the_pin(self) -> None:
        self._ensure("", "0.166.0").assert_called_once_with("@openai/codex@0.166.0")
        self.ensure_published.assert_called_once_with("@openai/codex", "0.166.0")

    def test_a_client_off_the_pin_is_replaced(self) -> None:
        self._ensure("0.165.0", "0.166.0").assert_called_once_with(
            "@openai/codex@0.166.0"
        )

    def test_a_client_whose_probe_fails_is_reinstalled(self) -> None:
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{os.environ['PATH']}"
        _program(self.bin, "codex", "exit 1\n")

        def install(_spec: str) -> None:
            _program(self.bin, "codex", "echo 'codex-cli 0.166.0'\n")

        with mock.patch.object(
            codex_mod, "npm_install_global", side_effect=install
        ) as installer:
            codex_mod.ensure_codex_present(self.repo)
        installer.assert_called_once_with("@openai/codex@0.166.0")

    def test_a_client_still_off_the_pin_after_the_install_fails(self) -> None:
        with self.assertRaises(codex_mod.CodexInstallError):
            self._ensure("", "0.165.0")

    def test_an_unreachable_registry_stops_before_npm_installs(self) -> None:
        self.ensure_published.side_effect = codex_mod.CodexInstallError(
            "npm cannot reach its registry"
        )
        with (
            mock.patch.object(codex_mod, "installed_version", return_value=""),
            mock.patch.object(codex_mod, "npm_install_global") as install,
            self.assertRaises(codex_mod.CodexInstallError),
        ):
            codex_mod.ensure_codex_present(self.repo)
        install.assert_not_called()

    def test_a_client_only_on_the_fallback_prefix_fails(self) -> None:
        prefix = "/fallback-prefix/bin"

        def install(_spec: str) -> None:
            os.environ["PATH"] = f"{prefix}{os.pathsep}{os.environ['PATH']}"

        def reported() -> str:
            return "0.166.0" if prefix in os.environ["PATH"] else ""

        with (
            mock.patch.object(codex_mod, "installed_version", side_effect=reported),
            mock.patch.object(codex_mod, "npm_install_global", side_effect=install),
            self.assertRaises(codex_mod.CodexInstallError),
        ):
            codex_mod.ensure_codex_present(self.repo)


if __name__ == "__main__":
    unittest.main()
