import re
import unittest
from pathlib import Path

from utils.annotations.message import warning
from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.applications.services.registry import is_explicit_truth
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_ROLE_PREFIX = "web-app-"
# Email *providers* call lookup('email') as the source of truth, not as
# dependent consumers, so they are exempt from the consumer rule. Both the
# active provider (web-app-stalwart) and the deprecated one (web-app-mailu,
# still in tree) qualify.
_EMAIL_PROVIDER_ROLES = {"web-app-stalwart", "web-app-mailu"}
_EMAIL_LOOKUP_RE = re.compile(r"""lookup\(\s*['"]email['"]""")
_SCAN_EXTENSIONS = {".yml", ".yaml", ".j2", ".py", ".sh", ".conf", ".env"}
# The email block is at the file root (top-level `email:`).
_EMAIL_KEY_RE = re.compile(r"^(\s*)email:\s*(#.*)?$")

_SILENCER_HINT = (
    "Silence per role by adding to meta/services.yml a "
    "'# nocheck: email' comment directly above an "
    "'email:' block with 'enabled: false' and 'shared: false'."
)


def _role_uses_email_lookup(role_path: Path) -> bool:
    for path in role_path.rglob("*"):  # nocheck: project-walk
        if not path.is_file() or path.suffix not in _SCAN_EXTENSIONS:
            continue
        try:
            text = read_text(str(path))
        except (OSError, UnicodeDecodeError):
            continue
        if _EMAIL_LOOKUP_RE.search(text):
            return True
    return False


def _email_service_conf(config_path: Path) -> dict:
    """Read ``services.email`` from the ``meta/services.yml``.

    The file root IS the services map; there is no ``compose.services``
    wrapper anymore.
    """
    if not config_path.is_file():
        return {}
    try:
        parsed = load_yaml_any(str(config_path), default_if_missing={}) or {}
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    svc = parsed.get("email", {}) or {}
    return svc if isinstance(svc, dict) else {}


def _has_opt_out(config_path: Path) -> bool:
    """Opt-out requires all three:

    1. services.email.enabled is False
    2. services.email.shared is False
    3. ``# nocheck: email`` on the nearest non-empty line directly
       above the ``email:`` key in the raw YAML source
    """
    if not config_path.is_file():
        return False
    try:
        text = read_text(str(config_path))
    except (OSError, UnicodeDecodeError):
        return False

    lines = text.splitlines()
    annotated = any(
        _EMAIL_KEY_RE.match(line)
        and is_suppressed_at(lines, idx + 1, "email", mode="line-above")
        for idx, line in enumerate(lines)
    )
    if not annotated:
        return False

    try:
        parsed = load_yaml_str(text) or {}
    except Exception:
        return False
    if not isinstance(parsed, dict):
        return False
    email = parsed.get("email", {}) or {}
    return email.get("enabled") is False and email.get("shared") is False


def _emit_missing_email_warning(root: Path, role_path: Path) -> None:
    config_file = role_path / ROLE_FILE_META_SERVICES
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
        root = PROJECT_ROOT
        roles_dir = root / "roles"
        self.assertTrue(
            roles_dir.is_dir(), f"'roles' directory not found at: {roles_dir}"
        )

        errors: list[str] = []
        for role_path in sorted(roles_dir.iterdir()):
            if not (role_path.is_dir() and role_path.name.startswith(_ROLE_PREFIX)):
                continue
            if role_path.name in _EMAIL_PROVIDER_ROLES:
                continue
            config = role_path / ROLE_FILE_META_SERVICES

            if _role_uses_email_lookup(role_path):
                svc = _email_service_conf(config)
                missing: list[str] = []
                if not is_explicit_truth(svc.get("enabled")):
                    missing.append("enabled: true")
                if not is_explicit_truth(svc.get("shared")):
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
        config = tmp_path / ROLE_FILE_META_SERVICES
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(text, encoding="utf-8")
        return config

    def test_opt_out_with_annotation_and_both_flags_false(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write(
                Path(tmp),
                "# nocheck: email\nemail:\n  enabled: false\n  shared: false\n",
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
                "# nocheck: email\nemail:\n  enabled: true\n  shared: false\n",
            )
            self.assertFalse(_has_opt_out(cfg))

    def test_opt_out_with_shared_true_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write(
                Path(tmp),
                "# nocheck: email\nemail:\n  enabled: false\n  shared: true\n",
            )
            self.assertFalse(_has_opt_out(cfg))

    def test_annotation_separated_by_blank_line_still_counts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write(
                Path(tmp),
                "# nocheck: email\n\nemail:\n  enabled: false\n  shared: false\n",
            )
            self.assertTrue(_has_opt_out(cfg))


if __name__ == "__main__":
    unittest.main()
