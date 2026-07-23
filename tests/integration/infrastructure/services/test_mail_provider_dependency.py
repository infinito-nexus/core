import re
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

# The default email provider is web-app-stalwart; web-app-mailu is a fully
# supported alternative selected via the MAIL_PROVIDER variable. Both are
# providers (they call lookup('email') as the source of truth, not as dependent
# consumers).
_PROVIDER_ROLES = {"web-app-stalwart", "web-app-mailu"}
_EMAIL_SERVICE_KEY = "email"

# Patterns that indicate an email dependency on the mail provider — either a
# direct role ref or the MAIL_PROVIDER selector consumers gate their email on.
_PROVIDER_REF_RE = re.compile(r"web-app-(?:stalwart|mailu)|MAIL_PROVIDER")
_EMAIL_LOOKUP_RE = re.compile(r"""lookup\(\s*['"]email['"]""")

# File extensions to scan within a role
_SCAN_EXTENSIONS = {".yml", ".yaml", ".j2", ".py", ".sh", ".conf", ".env"}


def _yaml_refs_skipping_required_by(data: object) -> tuple[bool, bool]:
    """Walk a parsed YAML structure for mail-provider refs and lookup('email'),
    but treat values inside any `required_by` subtree as inert. `required_by`
    expresses inverse coverage metadata for the deploy verifier, not a
    "consumer of the mail provider" relation."""
    refs_provider = False
    refs_email = False

    def walk(node: object, inside_required_by: bool) -> None:
        nonlocal refs_provider, refs_email
        if refs_provider and refs_email:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, inside_required_by or k == "required_by")
        elif isinstance(node, list):
            for item in node:
                walk(item, inside_required_by)
        elif isinstance(node, str) and not inside_required_by:
            if not refs_provider and _PROVIDER_REF_RE.search(node):
                refs_provider = True
            if not refs_email and _EMAIL_LOOKUP_RE.search(node):
                refs_email = True

    walk(data, False)
    return refs_provider, refs_email


def _scan_role(role_path: Path) -> tuple[bool, bool]:
    """Return (refs_provider, refs_email_lookup) for all scannable files in *role_path*."""
    refs_provider = False
    refs_email = False
    meta_services_yml = role_path / ROLE_FILE_META_SERVICES
    for path in role_path.rglob("*"):  # nocheck: project-walk
        if not path.is_file() or path.suffix not in _SCAN_EXTENSIONS:
            continue
        if path == meta_services_yml:
            data = load_yaml_any(str(path), default_if_missing={})
            yml_provider, yml_email = _yaml_refs_skipping_required_by(data)
            refs_provider = refs_provider or yml_provider
            refs_email = refs_email or yml_email
        else:
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if not refs_provider and _PROVIDER_REF_RE.search(text):
                refs_provider = True
            if not refs_email and _EMAIL_LOOKUP_RE.search(text):
                refs_email = True
        if refs_provider and refs_email:
            break
    return refs_provider, refs_email


class TestMailProviderServiceDependency(unittest.TestCase):
    """Every role that references the mail provider (web-app-stalwart /
    web-app-mailu) or calls lookup('email', ...) must declare services.email
    with enabled: true and shared: true in its meta/services.yml."""

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

    def test_provider_dependents_declare_email_service(self):
        errors = []
        for role_path in sorted(self.roles_root.iterdir()):
            if not role_path.is_dir():
                continue
            role_name = role_path.name
            if role_name in _PROVIDER_ROLES:
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

            refs_provider, refs_email_lookup = _scan_role(role_path)
            if not refs_provider and not refs_email_lookup:
                continue

            reasons = []
            if refs_provider:
                reasons.append("references the mail provider")
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
                "Roles that depend on the mail provider must declare "
                "services.email with enabled: true and shared: true:\n\n"
                + "\n".join(errors)
            )


if __name__ == "__main__":
    unittest.main()
