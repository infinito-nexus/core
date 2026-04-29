import re
import unittest
from pathlib import Path

import yaml

_MAILU_ROLE = "web-app-mailu"
_EMAIL_SERVICE_KEY = "email"

# Patterns that indicate an email dependency on Mailu
_MAILU_REF_RE = re.compile(r"web-app-mailu")
_EMAIL_LOOKUP_RE = re.compile(r"""lookup\(\s*['"]email['"]""")

# File extensions to scan within a role
_SCAN_EXTENSIONS = {".yml", ".yaml", ".j2", ".py", ".sh", ".conf", ".env"}


def _scan_role(role_path: Path) -> tuple[bool, bool]:
    """Return (refs_mailu, refs_email_lookup) for all scannable files in *role_path*."""
    refs_mailu = False
    refs_email = False
    for path in role_path.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not refs_mailu and _MAILU_REF_RE.search(text):
            refs_mailu = True
        if not refs_email and _EMAIL_LOOKUP_RE.search(text):
            refs_email = True
        if refs_mailu and refs_email:
            break
    return refs_mailu, refs_email


class TestMailuServiceDependency(unittest.TestCase):
    """Every role that references 'web-app-mailu' or calls lookup('email', ...)
    must declare services.email with enabled: true and shared: true
    in its config/main.yml."""

    PROJECT_ROOT = Path(__file__).resolve().parents[3]

    def setUp(self):
        self.roles_root = self.PROJECT_ROOT / "roles"
        self.assertTrue(
            self.roles_root.is_dir(),
            f"Roles directory not found: {self.roles_root}",
        )

    def _email_service_conf(self, config_path: Path) -> dict:
        if not config_path.is_file():
            return {}
        content = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return content.get(_EMAIL_SERVICE_KEY, {}) or {}

    def test_mailu_dependents_declare_email_service(self):
        errors = []
        for role_path in sorted(self.roles_root.iterdir()):
            if not role_path.is_dir():
                continue
            role_name = role_path.name
            if role_name == _MAILU_ROLE:
                continue
            # Email transport providers (msmtp, smtp/postfix) and the
            # email-alerting / mail-health roles implement or directly
            # service the email subsystem; they call lookup('email') as the
            # source of truth, not as dependent consumers. Exempt them.
            if (
                role_name.startswith("sys-svc-mail")
                or role_name == "sys-ctl-alm-email"
                or role_name == "sys-ctl-hlth-msmtp"
            ):
                continue

            config_path = role_path / "meta" / "services.yml"
            if not config_path.is_file():
                continue

            refs_mailu, refs_email_lookup = _scan_role(role_path)
            if not refs_mailu and not refs_email_lookup:
                continue

            reasons = []
            if refs_mailu:
                reasons.append("references 'web-app-mailu'")
            if refs_email_lookup:
                reasons.append("calls lookup('email', ...)")
            reason_str = " and ".join(reasons)

            email_svc = self._email_service_conf(config_path)
            rel = config_path.relative_to(self.PROJECT_ROOT)

            if not email_svc.get("enabled"):
                errors.append(
                    f"[{role_name}] {reason_str} but "
                    f"services.email.enabled is not true in {rel}"
                )
            if not email_svc.get("shared"):
                errors.append(
                    f"[{role_name}] {reason_str} but "
                    f"services.email.shared is not true in {rel}"
                )

        if errors:
            self.fail(
                "Roles that depend on Mailu must declare "
                "services.email with enabled: true and shared: true:\n\n"
                + "\n".join(errors)
            )


if __name__ == "__main__":
    unittest.main()
