import re
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_MAILU_ROLE = "web-app-mailu"
_EMAIL_SERVICE_KEY = "email"

# Patterns that indicate an email dependency on Mailu
_MAILU_REF_RE = re.compile(r"web-app-mailu")
_EMAIL_LOOKUP_RE = re.compile(r"""lookup\(\s*['"]email['"]""")

# File extensions to scan within a role
_SCAN_EXTENSIONS = {".yml", ".yaml", ".j2", ".py", ".sh", ".conf", ".env"}


def _yaml_refs_skipping_required_by(data: object) -> tuple[bool, bool]:
    """Walk a parsed YAML structure for mailu refs and lookup('email'), but
    treat values inside any `required_by` subtree as inert. `required_by`
    expresses inverse coverage metadata for the deploy verifier, not a
    "consumer of mailu" relation."""
    refs_mailu = False
    refs_email = False

    def walk(node: object, inside_required_by: bool) -> None:
        nonlocal refs_mailu, refs_email
        if refs_mailu and refs_email:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, inside_required_by or k == "required_by")
        elif isinstance(node, list):
            for item in node:
                walk(item, inside_required_by)
        elif isinstance(node, str) and not inside_required_by:
            if not refs_mailu and _MAILU_REF_RE.search(node):
                refs_mailu = True
            if not refs_email and _EMAIL_LOOKUP_RE.search(node):
                refs_email = True

    walk(data, False)
    return refs_mailu, refs_email


def _scan_role(role_path: Path) -> tuple[bool, bool]:
    """Return (refs_mailu, refs_email_lookup) for all scannable files in *role_path*."""
    refs_mailu = False
    refs_email = False
    meta_services_yml = role_path / ROLE_FILE_META_SERVICES
    for path in role_path.rglob("*"):  # nocheck: project-walk
        if not path.is_file() or path.suffix not in _SCAN_EXTENSIONS:
            continue
        if path == meta_services_yml:
            data = load_yaml_any(str(path), default_if_missing={})
            yml_mailu, yml_email = _yaml_refs_skipping_required_by(data)
            refs_mailu = refs_mailu or yml_mailu
            refs_email = refs_email or yml_email
        else:
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
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

    def setUp(self):
        self.roles_root = PROJECT_ROOT / "roles"
        self.assertTrue(
            self.roles_root.is_dir(),
            f"Roles directory not found: {self.roles_root}",
        )

    def _email_service_conf(self, config_path: Path) -> dict:
        if not config_path.is_file():
            return {}
        content = load_yaml_any(config_path) or {}
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
            if role_name.startswith("sys-svc-mail") or role_name in {
                "sys-ctl-alm-email",
                "sys-ctl-hlth-msmtp",
            }:
                continue

            config_path = role_path / ROLE_FILE_META_SERVICES
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
            rel = config_path.relative_to(PROJECT_ROOT)

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
