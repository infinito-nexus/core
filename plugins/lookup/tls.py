# lookup_plugins/tls.py
#
# STRICT TLS resolver (without SAN/cert identity planning).
#
# Certificate identity planning (SAN list, cert/key paths) is moved to:
#   lookup_plugins/cert.py

from __future__ import annotations

from typing import Any, Dict, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.tls_common import (
    AVAILABLE_FLAVORS,
    as_str,
    collect_domains_for_app,
    require,
    resolve_enabled,
    resolve_mode,
    resolve_term,
    uniq_preserve,
    want_get,
)
from utils.cache.applications import get_merged_applications
from utils.cache.domains import get_merged_domains


class LookupModule(LookupBase):
    def run(self, terms, variables: Optional[dict] = None, **kwargs):
        variables = variables or {}

        # New API: want-path is the 2nd positional term.
        # Legacy 'want=' kwarg is ignored (no error) to keep tasks noise-free.
        if not terms or len(terms) not in (1, 2):
            raise AnsibleError(
                "tls: one or two terms required: (domain|application_id[, want_path])"
            )

        term = as_str(terms[0])
        if not term:
            raise AnsibleError("tls: term is empty")

        want = as_str(terms[1]).strip() if len(terms) == 2 else ""

        domains = get_merged_domains(
            variables=variables,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )
        applications = get_merged_applications(
            variables=variables,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )
        enabled_default = require(variables, "TLS_ENABLED", (bool, int))
        mode_default = as_str(require(variables, "TLS_MODE", str))

        if mode_default not in AVAILABLE_FLAVORS:
            raise AnsibleError(
                f"tls: TLS_MODE must be one of {sorted(AVAILABLE_FLAVORS)}, got '{mode_default}'"
            )

        forced_mode = as_str(kwargs.get("mode", "auto")).lower()

        app_id, primary_domain = resolve_term(
            term,
            domains=domains,
            applications=applications,
            forced_mode=forced_mode,
            err_prefix="tls",
        )

        all_domains = collect_domains_for_app(domains, app_id, err_prefix="tls")
        all_domains = (
            uniq_preserve([primary_domain] + all_domains)
            if all_domains
            else [primary_domain]
        )

        app = applications.get(app_id, {})
        if not isinstance(app, dict):
            app = {}

        enabled = resolve_enabled(app, bool(enabled_default))
        mode = resolve_mode(app, enabled, mode_default, err_prefix="tls")

        if mode not in {"off"} | AVAILABLE_FLAVORS:
            raise AnsibleError(f"tls: unsupported mode '{mode}' for app '{app_id}'")

        web_protocol = "https" if enabled else "http"
        websocket_protocol = "wss" if enabled else "ws"
        web_port = 443 if enabled else 80
        base_url = f"{web_protocol}://{primary_domain}/"

        resolved: Dict[str, Any] = {
            "application_id": app_id,
            "domain": primary_domain,
            "enabled": enabled,
            "mode": mode,
            "domains": {"primary": primary_domain, "all": all_domains},
            "protocols": {"web": web_protocol, "websocket": websocket_protocol},
            "ports": {"web": web_port},
            "url": {"base": base_url},
        }

        if want:
            return [want_get(resolved, want)]
        return [resolved]
