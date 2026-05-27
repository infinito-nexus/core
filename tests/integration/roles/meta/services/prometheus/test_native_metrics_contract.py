"""Integration guard: ``services.prometheus.native_metrics.enabled``
in ``roles/<role>/meta/services.yml`` MUST be consistent with the
presence of ``roles/<role>/templates/prometheus.yml.j2``.

Companion to :mod:`tests.integration.roles.meta.services.prometheus.test_role_wiring`.
That module's ``TestNativeAppMetrics`` class spot-checks the three
known native-metrics roles (gitea, mattermost, matrix) for the
presence and shape of their scrape fragments. This module enforces
the *bidirectional* contract across the entire roles tree so a new
native-metrics role cannot drift into either failure mode.

Rationale
---------

``services.prometheus.native_metrics.enabled`` is consumed in two
places that must agree:

1. App side (``env.j2`` / ``homeserver.yaml.j2``): the flag flips the
   app's own ``/metrics`` endpoint on or off.
2. Prometheus side (:mod:`plugins.lookup.native_metrics_apps`): the
   lookup only includes a role's native scrape job when BOTH the flag
   is true AND ``roles/<role>/templates/prometheus.yml.j2`` exists.

If only one side is present the contract silently drifts:

* flag true, fragment missing → app exposes ``/metrics`` but nothing
  scrapes it; the endpoint is unreachable from prometheus.
* fragment present, flag not true → scrape job ships in the rendered
  ``prometheus.yml`` but the app's ``/metrics`` is off, so the target
  reports ``up=0`` and the parameterised native-metrics Playwright
  assertion fails on every deploy.

Both directions are therefore a hard error.

Required shape
--------------

For a role::

    services:
      prometheus:
        native_metrics:
          enabled: true            # IFF roles/<role>/templates/prometheus.yml.j2 exists

Exemption
---------

A ``# nocheck: native-metrics`` marker in the comment block directly
above the ``prometheus:`` key (no blank line between marker and key)
suppresses both directions for that role. Use this for prepared-but-
default-off fragments — e.g. ``web-app-mattermost`` ships the fragment
so the operator can flip the flag later without a code change.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
FRAGMENT_RELPATH = "templates/prometheus.yml.j2"

_RULE = "native-metrics"
_TARGET_KEY = "prometheus"


def _prometheus_block_is_suppressed(file_path: Path) -> bool:
    """Return True iff the comment block directly above the top-level
    ``prometheus:`` key carries a ``# nocheck: native-metrics`` marker.

    A blank line between the marker and the key breaks the association,
    matching the catalog's "comment block above" semantic.
    """
    pending = False
    for raw_line in read_text(str(file_path)).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            if line_has_rule(raw_line, _RULE):
                pending = True
            continue
        if not stripped:
            pending = False
            continue
        is_top_level = not raw_line.startswith((" ", "\t"))
        if is_top_level and ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            if key == _TARGET_KEY:
                return pending
        pending = False
    return False


def _native_metrics_enabled(data: object) -> bool:
    """Return True iff ``services.prometheus.native_metrics.enabled``
    resolves to literal ``True``. Any other shape (missing, ``False``,
    Jinja string) counts as "not enabled" for the forward direction."""
    if not isinstance(data, dict):
        return False
    prometheus_block = data.get(_TARGET_KEY)
    if not isinstance(prometheus_block, dict):
        return False
    native_metrics = prometheus_block.get("native_metrics")
    if not isinstance(native_metrics, dict):
        return False
    return native_metrics.get("enabled") is True


class TestPrometheusNativeMetricsContract(unittest.TestCase):
    def test_flag_matches_fragment(self) -> None:
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            services_file = role_dir / ROLE_FILE_META_SERVICES
            if not services_file.is_file():
                continue
            try:
                data = load_yaml_any(services_file, default_if_missing={}) or {}
            except Exception as exc:
                offenders.append(f"{role_name}: YAML parse error: {exc}")
                continue

            if _prometheus_block_is_suppressed(services_file):
                continue

            enabled = _native_metrics_enabled(data)
            fragment_exists = (role_dir / FRAGMENT_RELPATH).is_file()

            if enabled and not fragment_exists:
                offenders.append(
                    f"{role_name}: services.prometheus.native_metrics.enabled=true "
                    f"but {FRAGMENT_RELPATH} is missing. Either create the "
                    f"scrape-config fragment or flip the flag to false."
                )
            elif fragment_exists and not enabled:
                offenders.append(
                    f"{role_name}: {FRAGMENT_RELPATH} exists but "
                    f"services.prometheus.native_metrics.enabled is not true. "
                    f"Enable the flag, delete the fragment, or add "
                    f"`# nocheck: {_RULE}` directly above `{_TARGET_KEY}:` "
                    f"for prepared-but-default-off fragments."
                )

        if offenders:
            self.fail(
                "native_metrics enabled flag and prometheus.yml.j2 fragment "
                "MUST be consistent:\n" + "\n".join(f"  - {o}" for o in offenders),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
