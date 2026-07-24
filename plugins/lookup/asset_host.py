from __future__ import annotations

from typing import Any

from ansible.plugins.lookup import LookupBase

from plugins.lookup.asset import resolve_host


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('asset_host') }}

    Returns the origin that lookup('asset', ...) resolves against for the
    current deployment (the internal CDN origin with web-svc-cdn flavor
    internal, else https://cdn.jsdelivr.net). Use it to derive the CSP
    script-/style-src origin from the same flavor decision the asset URLs
    use, so the whitelist never drifts from where the assets load.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        return [resolve_host(variables, self._loader, getattr(self, "_templar", None))]
