from __future__ import annotations
import os
import sys
from typing import Iterable, Sequence
from ansible.errors import AnsibleFilterError
from utils.applications.config import (
    get,
    AppConfigKeyError,
    ConfigEntryNotSetError,
)
from utils.get_url import get_url  # returns "<protocol>://<domain>"


# --- Locate project root that contains `utils/` dynamically (up to 5 levels) ---
def _ensure_utils_on_path():
    here = os.path.dirname(__file__)
    for depth in range(1, 6):
        candidate = os.path.abspath(os.path.join(here, *([".."] * depth)))
        if os.path.isdir(os.path.join(candidate, "utils")):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            return
    # If not found, imports below will raise a clear error


_ensure_utils_on_path()


def _stable_dedup(items: Sequence[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _iter_domains(v) -> Iterable[str]:
    """Yield domains from str | list/tuple[str] | dict[*, str|list|tuple]."""
    if v is None:
        return
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for val in v.values():
            yield from _iter_domains(val)
    elif isinstance(v, (list, tuple)):
        for val in v:
            yield from _iter_domains(val)
    else:
        raise AnsibleFilterError(
            "redirect_uris: domain_value must be str, list/tuple[str], or dict mapping to those"
        )


def redirect_uris(
    domains: dict,
    applications: dict,
    web_protocol: str = "https",
    wildcard: str = "/*",
    features: Iterable[str] = (
        "services.oauth2.enabled",
        "services.oidc.enabled",
    ),
    dedup: bool = True,
) -> list[str]:
    """
    Build redirect URIs using:
      - get(applications, app_id, dotted_key, default) for feature gating
      - get_url(domains_subset, app_id, web_protocol) to form "<proto>://<domain>"

    For domain lists, we call get_url() once per domain by passing a minimal
    per-app subset like {app_id: "example.org"} to preserve your original
    'one entry per domain' behavior.
    """
    if not isinstance(domains, dict):
        raise AnsibleFilterError(
            "redirect_uris: 'domains' must be a dict mapping app_id -> domain or list of domains"
        )

    uris: list[str] = []

    for app_id, domain_value in domains.items():
        # Feature check via get
        try:
            has_feature = any(
                bool(get(applications, app_id, f, False)) for f in features
            )
        except (AppConfigKeyError, ConfigEntryNotSetError):
            has_feature = False

        if not has_feature:
            continue

        # Normalize to iterable of domains
        doms = list(_iter_domains(domain_value))

        for d in doms:
            # Use get_url() to produce "<proto>://<domain>"
            # Pass a minimal per-app mapping so get_domain() resolves to 'd'
            try:
                url = get_url({app_id: d}, app_id, web_protocol)
            except Exception as e:
                raise AnsibleFilterError(
                    f"redirect_uris: get_url failed for app '{app_id}' with domain '{d}': {e}"
                )
            uris.append(f"{url}{wildcard}")

    return _stable_dedup(uris) if dedup else uris


class FilterModule(object):
    """Infinito.Nexus redirect URI builder (uses get + get_url)"""

    def filters(self):
        return {
            "redirect_uris": redirect_uris,
        }
