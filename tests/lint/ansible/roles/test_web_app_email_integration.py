import re
import unittest
from pathlib import Path

import yaml

from utils.annotations.message import warning


_ROLE_PREFIX = "web-app-"
_MAILU_ROLE = "web-app-mailu"
_EMAIL_LOOKUP_RE = re.compile(r"""lookup\(\s*['"]email['"]""")
_SCAN_EXTENSIONS = {".yml", ".yaml", ".j2", ".py", ".sh", ".conf", ".env"}
# Post-req-008 the email block is at the file root (top-level `email:`)
# rather than nested under `compose.services.email:`. Match either shape so
# this lint keeps working during the long tail of role migrations.
_EMAIL_KEY_RE = re.compile(r"^(\s*)email:\s*(#.*)?$")
_ANNOTATION_RE = re.compile(r"^\s*#\s*noqa:\s*email\b")

_SILENCER_HINT = (
    "Silence per role by adding to meta/services.yml a "
    "'# noqa: email' comment directly above an 'email:' block with "
    "'enabled: false' and 'shared: false'."
)


def repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("Repository root not found from test path.")


def _role_uses_email_lookup(role_path: Path) -> bool:
    for path in role_path.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _EMAIL_LOOKUP_RE.search(text):
            return True
    return False


def _email_service_conf(config_path: Path) -> dict:
    """Read ``services.email`` from the post-req-008 ``meta/services.yml``.

    The file root IS the services map; there is no ``compose.services``
    wrapper anymore.
    """
    if not config_path.is_file():
        return {}
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    svc = parsed.get("email", {}) or {}
    return svc if isinstance(svc, dict) else {}


def _has_opt_out(config_path: Path) -> bool:
    """Opt-out requires all three:

    1. services.email.enabled is False
    2. services.email.shared is False
    3. ``# noqa: email`` on the nearest non-empty line directly above the
       ``email:`` key in the raw YAML source
    """
    if not config_path.is_file():
        return False
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return False

    lines = text.splitlines()
    annotated = False
    for idx, line in enumerate(lines):
        if not _EMAIL_KEY_RE.match(line):
            continue
        prev_idx = idx - 1
        while prev_idx >= 0 and lines[prev_idx].strip() == "":
            prev_idx -= 1
        if prev_idx >= 0 and _ANNOTATION_RE.match(lines[prev_idx]):
            annotated = True
            break
    if not annotated:
        return False

    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(parsed, dict):
        return False
    email = parsed.get("email", {}) or {}
    return email.get("enabled") is False and email.get("shared") is False


def _emit_missing_email_warning(root: Path, role_path: Path) -> None:
    config_file = role_path / "meta" / "services.yml"
    if config_file.is_file():
        relative = config_file.relative_to(root).as_posix()
    else:
        relative = role_path.relative_to(root).as_posix()
    message = (
        f"{role_path.name} has no lookup('email', application_id) integration. "
        "Web apps typically need email to send notifications, password resets, "
        "and activation links to their users (non-blocking). " + _SILENCER_HINT
    )
    warning(message, title="Missing Email Integration", file=relative)


class TestWebAppRolesIntegrateEmail(unittest.TestCase):
    """Two behaviours in a single sweep over roles/web-app-*:

    * Roles that call ``lookup('email', ...)`` **must** declare
      ``services.email`` with ``enabled: true`` AND ``shared: true``
      in ``config/main.yml``. Missing declarations fail the test hard.
    * Roles that do **not** call ``lookup('email', ...)`` and have no
      explicit opt-out block emit a non-blocking warning annotation.
    """

    def test_web_app_roles_email(self):
        root = repo_root()
        roles_dir = root / "roles"
        self.assertTrue(
            roles_dir.is_dir(), f"'roles' directory not found at: {roles_dir}"
        )

        errors: list[str] = []
        for role_path in sorted(roles_dir.iterdir()):
            if not (role_path.is_dir() and role_path.name.startswith(_ROLE_PREFIX)):
                continue
            if role_path.name == _MAILU_ROLE:
                continue
            config = role_path / "meta" / "services.yml"

            if _role_uses_email_lookup(role_path):
                svc = _email_service_conf(config)
                missing: list[str] = []
                if svc.get("enabled") is not True:
                    missing.append("enabled: true")
                if svc.get("shared") is not True:
                    missing.append("shared: true")
                if missing:
                    rel = (
                        config.relative_to(root).as_posix()
                        if config.is_file()
                        else role_path.relative_to(root).as_posix()
                    )
                    errors.append(
                        f"[{role_path.name}] {rel}: calls lookup('email', ...) "
                        f"but services.email is missing {', '.join(missing)}"
                    )
                continue

            if _has_opt_out(config):
                continue
            _emit_missing_email_warning(root, role_path)

        if errors:
            self.fail(
                "Roles that call lookup('email', ...) must declare "
                "services.email with enabled: true AND shared: true:\n\n"
                + "\n".join(errors)
            )


class TestOptOutDetection(unittest.TestCase):
    """Verify _has_opt_out semantics in isolation."""

    def _write(self, tmp_path: Path, text: str) -> Path:
        config = tmp_path / "meta" / "services.yml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(text, encoding="utf-8")
        return config

    def test_opt_out_with_annotation_and_both_flags_false(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write(
                Path(tmp),
                "# noqa: email\nemail:\n  enabled: false\n  shared: false\n",
            )
            self.assertTrue(_has_opt_out(cfg))

    def test_opt_out_missing_annotation_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write(
                Path(tmp),
                "email:\n  enabled: false\n  shared: false\n",
            )
            self.assertFalse(_has_opt_out(cfg))

    def test_opt_out_with_enabled_true_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write(
                Path(tmp),
                "# noqa: email\nemail:\n  enabled: true\n  shared: false\n",
            )
            self.assertFalse(_has_opt_out(cfg))

    def test_opt_out_with_shared_true_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write(
                Path(tmp),
                "# noqa: email\nemail:\n  enabled: false\n  shared: true\n",
            )
            self.assertFalse(_has_opt_out(cfg))

    def test_annotation_separated_by_blank_line_still_counts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write(
                Path(tmp),
                "# noqa: email\n\nemail:\n  enabled: false\n  shared: false\n",
            )
            self.assertTrue(_has_opt_out(cfg))


if __name__ == "__main__":
    unittest.main()
