from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.role_path_by_app_id import abs_role_path_by_application_id
from utils.cache.files import read_text

_JSDELIVR = "https://cdn.jsdelivr.net"


def resolve_host(variables, loader, templar) -> str:
    """The asset host for the current deployment: the internal CDN origin
    when web-svc-cdn is deployed with flavor internal, else jsdelivr."""
    if "web-svc-cdn" not in (variables.get("group_names") or []):
        return _JSDELIVR
    flavor = lookup_loader.get("config", loader=loader, templar=templar).run(
        ["web-svc-cdn", "services.cdn.flavor"], variables=variables
    )[0]
    if str(flavor).strip().lower() != "internal":
        return _JSDELIVR
    domain = lookup_loader.get("domain", loader=loader, templar=templar).run(
        ["web-svc-cdn"], variables=variables
    )[0]
    return f"https://{domain}"


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('asset', application_id, package, path_within_package) }}

    Resolves a browser-facing URL for a frontend dependency declared in the
    role's own package-lock.json, mirroring jsdelivr's npm path scheme so the
    internal and external forms differ only by host:

      internal (web-svc-cdn deployed, flavor internal):
        cdn.<domain>/npm/<package>@<locked-version>/<path>
      external (no web-svc-cdn, or flavor external):
        cdn.jsdelivr.net/npm/<package>@<locked-version>/<path>

    The version is read from roles/<application_id>/files/package-lock.json, so
    the URL is always the exact pinned, lockfile-reproducible version.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms) != 3:
            raise AnsibleError(
                "lookup('asset', application_id, package, path) expects 3 terms"
            )
        application_id, package, path = (str(t) for t in terms)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        version = self._locked_version(application_id, package)
        host = resolve_host(variables, self._loader, getattr(self, "_templar", None))
        return [f"{host}/npm/{package}@{version}/{path.lstrip('/')}"]

    def _locked_version(self, application_id: str, package: str) -> str:
        lock = (
            Path(abs_role_path_by_application_id(application_id))
            / "files"
            / "package-lock.json"
        )
        if not lock.is_file():
            raise AnsibleError(
                f"lookup('asset'): {lock} not found; declare {package} in the "
                f"role's files/package.json and commit its files/package-lock.json"
            )
        data = json.loads(read_text(str(lock)))
        entry = (data.get("packages") or {}).get(f"node_modules/{package}")
        if not entry or "version" not in entry:
            raise AnsibleError(f"lookup('asset'): {package} not pinned in {lock}")
        return str(entry["version"])
