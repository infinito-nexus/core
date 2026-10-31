"""Lint: the ERPNext core role holds no name a consumer reserved on its site.

The store (``web-app-cst-store``) and the security check
(``web-app-cst-security-check``) build their structure at runtime on the site
of ``web-app-erpnext``, each under the names below. A reserved prefix or name
in any file of the core role means the core role creates or relies on consumer
structure, which belongs in the consumer's own repository.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

ROLE = "web-app-erpnext"
STORE = "store"
SECURITY_CHECK = "security check"

STORE_PREFIXES = ("INF::", "INF-PR-")
STORE_SCRIPT_PREFIX = "Platform-"
STORE_NAMES = (
    "Sales Order Lifecycle",
    "Infinito Sales Invoice",
    "Provisioning Bot",
)
STORE_WEBHOOKS = (
    "infinito-invoice-submitted",
    "infinito-payment-entry-submitted",
    "infinito-sales-order-active",
    "infinito-sales-order-provisioning",
    "infinito-sales-order-state-change",
)
STORE_CUSTOM_FIELDS = (
    "custom_auto_topup_amount",
    "custom_auto_topup_enabled",
    "custom_auto_topup_threshold",
    "custom_availability",
    "custom_capacity_gb",
    "custom_cpu_vcores",
    "custom_device_subtype",
    "custom_dns_provider_id",
    "custom_keycloak_sub",
    "custom_kind",
    "custom_linux_compatible",
    "custom_max_negative_balance",
    "custom_memory_gb",
    "custom_platform_bundle_id",
    "custom_platform_label",
    "custom_platform_profile",
    "custom_registrar_provider_id",
    "custom_sales_partner",
    "custom_sepa_mandate_id",
    "custom_storage_gb",
    "custom_tld",
    "custom_workflow_version",
)
SECURITY_CHECK_PREFIXES = ("custom_secchk_", "security-check-")
SECURITY_CHECK_NAME = "Security Check"

CORE_NAMES = (
    "app_name = 'infinito_rbac'",
    "app_title = 'Infinito RBAC'",
    "THEME_FILE = 'infinito-design.css'",
    "HEAD_OPEN = '<!--infinito-design-->'",
    "site: next.erp.infinito.example",
    "consumers: web-app-cst-store, web-app-cst-security-check",
    "Security check and store build on the site.",
    "protected: platform_administrator",
    "ldap_custom_group_search: uid={0}",
)


def _prefix(prefix: str) -> re.Pattern[str]:
    return re.compile(re.escape(prefix))


def _name(name: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(name)}\b")


RESERVED: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    *((STORE, prefix, _prefix(prefix)) for prefix in STORE_PREFIXES),
    (
        STORE,
        STORE_SCRIPT_PREFIX,
        re.compile(rf"\b{re.escape(STORE_SCRIPT_PREFIX)}[A-Z]"),
    ),
    *(
        (STORE, name, _name(name))
        for name in (*STORE_NAMES, *STORE_WEBHOOKS, *STORE_CUSTOM_FIELDS)
    ),
    *((SECURITY_CHECK, prefix, _prefix(prefix)) for prefix in SECURITY_CHECK_PREFIXES),
    (SECURITY_CHECK, SECURITY_CHECK_NAME, _name(SECURITY_CHECK_NAME)),
)


def role_files() -> Iterator[tuple[str, str]]:
    """Yield ``(path, content)`` for every text file of the core role.

    Yields:
        The path relative to the repository root and the file's content.
    """
    root = PROJECT_ROOT / "roles" / ROLE
    for path in iter_project_files():
        if not Path(path).is_relative_to(root):
            continue
        try:
            text = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        yield os.path.relpath(path, str(PROJECT_ROOT)), text


def offenders(files: Iterable[tuple[str, str]]) -> list[str]:
    """Return one ``<path>:<line>: <consumer> reserves <name>`` finding per hit.

    Args:
        files: ``(path, content)`` pairs to scan.
    """
    findings = []
    for path, text in files:
        for number, line in enumerate(text.splitlines(), 1):
            findings.extend(
                f"{path}:{number}: {consumer} reserves {label!r}"
                for consumer, label, pattern in RESERVED
                if pattern.search(line)
            )
    return findings


class TestConsumerNamespaces(unittest.TestCase):
    def test_the_core_role_holds_no_reserved_name(self) -> None:
        findings = offenders(role_files())
        self.assertEqual(
            [],
            findings,
            f"roles/{ROLE} holds names a consumer reserved on the ERPNext site; "
            "move that structure into the consumer's own repository:\n"
            + "\n".join(f"  - {finding}" for finding in findings),
        )

    def test_the_scan_reaches_the_core_role(self) -> None:
        self.assertNotEqual([], list(role_files()))

    def test_every_reserved_name_fails_the_lint(self) -> None:
        for consumer, label, pattern in RESERVED:
            sample = label if pattern.search(label) else f"{label}Sample"
            with self.subTest(name=label):
                self.assertEqual(
                    [f"control.yml:2: {consumer} reserves {label!r}"],
                    offenders([("control.yml", f"---\nname: {sample}\n")]),
                )

    def test_names_of_the_core_role_pass_the_lint(self) -> None:
        self.assertEqual([], offenders([("control.py", "\n".join(CORE_NAMES))]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
