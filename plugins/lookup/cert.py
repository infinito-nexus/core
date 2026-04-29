# lookup_plugins/cert.py
#
# Certificate planning lookup for Infinito.Nexus:
# - Computes certificate file paths (cert/key/ca)
# - Computes effective SAN list (domains.san)
# - Supports self-signed scope: "app" | "global"
#
# See utils/tls_common.py for shared resolution logic.

from __future__ import annotations

import os
from typing import Any, Dict, Optional, List

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.jinja_strict import render_strict
from utils.cache.applications import get_merged_applications
from utils.cache.domains import get_merged_domains
from utils.tls_common import (
    AVAILABLE_FLAVORS,
    as_str,
    collect_domains_for_app,
    override_san_list,
    require,
    resolve_enabled,
    resolve_le_name,
    resolve_mode,
    resolve_term,
    uniq_preserve,
    want_get,
)

LE_FULLCHAIN = "fullchain.pem"
LE_PRIVKEY = "privkey.pem"


def _join(*parts: Any) -> str:
    cleaned = [str(p).strip() for p in parts if str(p).strip()]
    return os.path.join(*cleaned) if cleaned else ""


def _require_current_play_domains_all_strict(variables: dict) -> List[str]:
    """
    STRICT FORMAT REQUIREMENT

    CURRENT_PLAY_DOMAINS_ALL MUST:
    - exist
    - be list[str]
    - be non-empty
    - contain only non-empty strings

    No fallback. No coercion. No dict support.
    """
    value = variables.get("CURRENT_PLAY_DOMAINS_ALL")

    if not isinstance(value, list):
        raise AnsibleError(
            "cert(strict): CURRENT_PLAY_DOMAINS_ALL must be of type list[str]. "
            f"Got {type(value).__name__}."
        )

    cleaned: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise AnsibleError(
                "cert(strict): CURRENT_PLAY_DOMAINS_ALL must contain only strings."
            )
        item = item.strip()
        if not item:
            raise AnsibleError(
                "cert(strict): CURRENT_PLAY_DOMAINS_ALL must not contain empty strings."
            )
        cleaned.append(item)

    if not cleaned:
        raise AnsibleError("cert(strict): CURRENT_PLAY_DOMAINS_ALL must not be empty.")

    return cleaned


class LookupModule(LookupBase):
    def run(self, terms, variables: Optional[dict] = None, **kwargs):
        variables = variables or {}

        # New API: want-path is the 2nd positional term.
        # Legacy 'want=' kwarg is ignored (no error) to keep tasks noise-free.
        if not terms or len(terms) not in (1, 2):
            raise AnsibleError(
                "cert: one or two terms required: (domain|application_id[, want_path])"
            )

        term = as_str(terms[0])
        if not term:
            raise AnsibleError("cert: term is empty")

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
                f"cert: TLS_MODE must be one of {sorted(AVAILABLE_FLAVORS)}, got '{mode_default}'"
            )

        forced_mode = as_str(kwargs.get("mode", "auto")).lower()
        app_id, primary_domain = resolve_term(
            term,
            domains=domains,
            applications=applications,
            forced_mode=forced_mode,
            err_prefix="cert",
        )

        app = applications.get(app_id, {})
        if not isinstance(app, dict):
            app = {}

        enabled = resolve_enabled(app, bool(enabled_default))
        mode = resolve_mode(app, enabled, mode_default, err_prefix="cert")

        cert_file = ""
        key_file = ""
        ca_file = ""
        san_domains: List[str] = []
        cert_id = ""
        scope = "app"

        if mode == "off":
            pass

        elif mode == "letsencrypt":
            le_live_raw = require(variables, "LETSENCRYPT_LIVE_PATH", str)
            le_live = render_strict(
                le_live_raw,
                variables=variables,
                var_name="LETSENCRYPT_LIVE_PATH",
                err_prefix="cert",
            )

            le_name = resolve_le_name(app, primary_domain)
            cert_id = le_name

            cert_file = _join(le_live, le_name, LE_FULLCHAIN)
            key_file = _join(le_live, le_name, LE_PRIVKEY)

            all_domains = collect_domains_for_app(domains, app_id, err_prefix="cert")
            all_domains = (
                uniq_preserve([primary_domain] + all_domains)
                if all_domains
                else [primary_domain]
            )

            san_override = override_san_list(app)
            if san_override is None:
                san_domains = all_domains[:]
            else:
                san_domains = uniq_preserve([primary_domain] + san_override)

        elif mode == "self_signed":
            ss_base_raw = require(variables, "TLS_SELFSIGNED_BASE_PATH", str)
            ss_base = render_strict(
                ss_base_raw,
                variables=variables,
                var_name="TLS_SELFSIGNED_BASE_PATH",
                err_prefix="cert",
            )

            ss_scope = as_str(variables.get("TLS_SELFSIGNED_SCOPE")).lower()
            if ss_scope not in {"app", "global"}:
                raise AnsibleError(
                    "cert: TLS_SELFSIGNED_SCOPE must be 'app' or 'global'"
                )

            scope = ss_scope

            if ss_scope == "global":
                cert_id = "global"
                cert_file = _join(ss_base, cert_id, LE_FULLCHAIN)
                key_file = _join(ss_base, cert_id, LE_PRIVKEY)

                # STRICT: list[str] only
                san_domains = _require_current_play_domains_all_strict(variables)

                # Ensure primary domain is always included
                if primary_domain:
                    san_domains = uniq_preserve([primary_domain] + san_domains)

            else:
                cert_id = app_id
                cert_file = _join(ss_base, app_id, primary_domain, LE_FULLCHAIN)
                key_file = _join(ss_base, app_id, primary_domain, LE_PRIVKEY)

                all_domains = collect_domains_for_app(
                    domains, app_id, err_prefix="cert"
                )
                all_domains = (
                    uniq_preserve([primary_domain] + all_domains)
                    if all_domains
                    else [primary_domain]
                )

                san_override = override_san_list(app)
                if san_override is None:
                    san_domains = all_domains[:]
                else:
                    san_domains = uniq_preserve([primary_domain] + san_override)

        else:
            raise AnsibleError(f"cert: unsupported mode '{mode}'")

        resolved: Dict[str, Any] = {
            "application_id": app_id,
            "domain": primary_domain,
            "enabled": enabled,
            "mode": mode,
            "scope": scope,
            "cert_id": cert_id,
            "domains": {"san": san_domains},
            "files": {"cert": cert_file, "key": key_file, "ca": ca_file},
        }

        if want:
            return [want_get(resolved, want)]

        return [resolved]
