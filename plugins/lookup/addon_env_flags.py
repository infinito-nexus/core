from __future__ import annotations

import re
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.cache.base import _render_with_templar
from utils.roles.applications.config import get

ENV_SUFFIX = "_ADDON_ENABLED"
_TRUE_TOKENS = {"true", "1", "yes", "on", "t", "y"}


def env_key(addon_id: str) -> str:
    """Mirror addon-gating.js envKey(): upper-case, non-alphanumeric runs -> '_'."""
    return re.sub(r"[^A-Z0-9]+", "_", str(addon_id).upper()) + ENV_SUFFIX


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_TOKENS


def _resolve_deployed_roles(variables, templar, applications):
    """Resolve TEST_E2E_PLAYWRIGHT_APPS (the deployed playwright role ids) to a set.
    Returns None when it cannot be resolved, in which case bridge-deployment
    gating is skipped (no behaviour change)."""
    raw = (variables or {}).get("TEST_E2E_PLAYWRIGHT_APPS")
    if raw is None:
        return None
    resolved = raw
    if isinstance(raw, str):
        try:
            resolved = _render_with_templar(
                raw, templar=templar, variables=variables, raw_applications=applications
            )
        except Exception:
            return None
    if isinstance(resolved, str):
        resolved = [r for r in re.split(r"[\s,]+", resolved.strip()) if r]
    if not isinstance(resolved, (list, tuple, set)):
        return None
    return {str(r).strip() for r in resolved if str(r).strip()}


def _any_bridge_partner_deployed(bridges, deployed_roles):
    """A bridged addon's partner counts as deployed iff some deployed role id
    equals or ends with the bridge name (web-app-<bridge>, web-svc-<bridge>, ...)."""
    for bridge in bridges:
        name = str(bridge).strip()
        if not name:
            continue
        variants = {name, name.replace("_", "-")}
        for role in deployed_roles:
            if role in variants or any(role.endswith("-" + v) for v in variants):
                return True
    return False


class LookupModule(LookupBase):
    """
    lookup('addon_env_flags', application_id)

    Single source of truth for the per-addon enable flags consumed by the
    Playwright addon-gating helper (``tests/addon-gating.js`` ->
    ``skipUnlessAddonEnabled``). Replaces the error-prone per-template Jinja
    loop: it resolves the materialised ``addons`` mapping for ``application_id``
    and returns one ``<ADDON_ID>_ADDON_ENABLED=<true|false>`` line per declared
    addon (sorted by env key, newline-joined), where the env-key derivation
    matches addon-gating.js exactly.

    A flag is ``true`` only when the addon is both ``enabled`` AND
    ``required``. Optional addons (``required: false``) are intentionally
    skipped by the spec suite — they are a variant axis, not a guaranteed
    surface — so their gate flag is ``false`` even when enabled.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('addon_env_flags', application_id) expects exactly one term."
            )

        application_id = terms[0]
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=variables)[0]
        addons = get(
            applications=applications,
            application_id=application_id,
            config_path="addons",
            strict=False,
            default={},
            skip_missing_app=True,
        )
        addons = _render_with_templar(
            addons,
            templar=templar,
            variables=variables,
            raw_applications=applications,
        )
        if not isinstance(addons, dict):
            addons = {}

        deployed_roles = _resolve_deployed_roles(variables, templar, applications)

        lines = []
        for addon_id in sorted(addons, key=env_key):
            spec = (
                addons.get(addon_id) if isinstance(addons.get(addon_id), dict) else {}
            )
            active = _is_enabled(spec.get("enabled", False)) and _is_enabled(
                spec.get("required", False)
            )
            if active and deployed_roles is not None:
                bridges = spec.get("bridges")
                if isinstance(bridges, list) and bridges:
                    active = _any_bridge_partner_deployed(bridges, deployed_roles)
            lines.append(f"{env_key(addon_id)}={'true' if active else 'false'}")

        return ["\n".join(lines)]
