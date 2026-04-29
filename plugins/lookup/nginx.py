# lookup_plugins/nginx.py
#
# Resolve nginx path configuration (lowercase keys) and (optionally) a domain-specific
# server config path placed under:
#
#   <servers_dir>/<protocol>/<domain>.conf
#
# New API (STRICT):
#   lookup('nginx', want_path [, domain ])
#
# Examples:
#   lookup('nginx', 'files.configuration')
#   lookup('nginx', 'files.domain', 'example.com')
#   lookup('nginx', 'files.domain', 'example.com', protocol='http')
#
# Notes:
# - want-path is ALWAYS the first positional argument
# - domain is optional and only affects domain-specific keys
# - want= kwarg is intentionally ignored

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.plugins.loader import lookup_loader

from utils.applications.config import get
from utils.cache.applications import get_merged_applications
from utils.tls_common import as_str, want_get


def _join(*parts: Any) -> str:
    cleaned = [str(p).strip() for p in parts if str(p).strip()]
    return os.path.join(*cleaned) if cleaned else ""


def _ensure_trailing_slash(p: str) -> str:
    p = p.strip()
    return p if not p or p.endswith("/") else p + "/"


def _normalize_protocol(value: str) -> str:
    v = as_str(value).strip().lower()
    if v in ("http", "https"):
        return v
    raise AnsibleError(
        f"nginx: invalid protocol override '{value}' (expected http|https)"
    )


def _dir_spec(path: str, mode: str) -> Dict[str, str]:
    path = as_str(path).strip()
    mode = as_str(mode).strip()
    if not path:
        raise AnsibleError("nginx: empty path in directories.ensure")
    if mode not in ("0700", "0755"):
        raise AnsibleError(
            f"nginx: invalid mode '{mode}' in directories.ensure (expected 0700|0755)"
        )
    return {"path": path, "mode": mode}


def _resolve_protocol_via_tls(
    *, domain: str, variables: dict, loader: Any, templar: Any
) -> str:
    try:
        tls_lookup = lookup_loader.get("tls", loader=loader, templar=templar)
    except Exception as exc:
        raise AnsibleError(f"nginx: failed to load tls lookup: {exc}") from exc

    protocol = tls_lookup.run([domain, "protocols.web"], variables=variables)[0]

    protocol_s = as_str(protocol).strip().lower()
    if protocol_s not in ("http", "https"):
        raise AnsibleError(
            f"nginx: unexpected protocol '{protocol_s}' for domain '{domain}'"
        )
    return protocol_s


class LookupModule(LookupBase):
    def run(self, terms, variables: Optional[dict] = None, **kwargs):
        variables = variables or {}
        terms = terms or []

        # STRICT API: want-path is mandatory
        if len(terms) not in (1, 2):
            raise AnsibleError("nginx: requires want_path [, domain]")

        want = as_str(terms[0]).strip()
        if not want:
            raise AnsibleError("nginx: want_path is empty")

        domain = as_str(terms[1]).strip() if len(terms) == 2 else ""

        applications = get_merged_applications(
            variables=variables,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        proxy_app_id = as_str(kwargs.get("proxy_app_id", "svc-prx-openresty")).strip()
        if not proxy_app_id:
            raise AnsibleError("nginx: proxy_app_id is empty")

        www_dir = get(applications, proxy_app_id, "volumes.www", strict=True)
        nginx_dir = get(applications, proxy_app_id, "volumes.nginx", strict=True)

        www_dir = _ensure_trailing_slash(as_str(www_dir))
        nginx_dir = _ensure_trailing_slash(as_str(nginx_dir))

        conf_dir = _ensure_trailing_slash(_join(nginx_dir, "conf.d"))
        global_dir = _ensure_trailing_slash(_join(conf_dir, "global"))
        servers_dir = _ensure_trailing_slash(_join(conf_dir, "servers"))
        servers_http_dir = _ensure_trailing_slash(_join(servers_dir, "http"))
        servers_https_dir = _ensure_trailing_slash(_join(servers_dir, "https"))
        maps_dir = _ensure_trailing_slash(_join(conf_dir, "maps"))
        streams_dir = _ensure_trailing_slash(_join(conf_dir, "streams"))

        data_html_dir = _ensure_trailing_slash(_join(www_dir, "public_html"))
        data_files_dir = _ensure_trailing_slash(_join(www_dir, "public_files"))
        data_cdn_dir = _ensure_trailing_slash(_join(www_dir, "public_cdn"))
        data_global_dir = _ensure_trailing_slash(_join(www_dir, "global"))

        cache_general_dir = "/tmp/cache_nginx_general/"
        cache_image_dir = "/tmp/cache_nginx_image/"

        ensure: List[Dict[str, str]] = [
            _dir_spec(nginx_dir, "0755"),
            _dir_spec(conf_dir, "0755"),
            _dir_spec(global_dir, "0755"),
            _dir_spec(servers_dir, "0755"),
            _dir_spec(servers_http_dir, "0755"),
            _dir_spec(servers_https_dir, "0755"),
            _dir_spec(maps_dir, "0755"),
            _dir_spec(streams_dir, "0755"),
            _dir_spec(www_dir, "0755"),
            _dir_spec(data_html_dir, "0755"),
            _dir_spec(data_files_dir, "0755"),
            _dir_spec(data_cdn_dir, "0755"),
            _dir_spec(data_global_dir, "0755"),
            _dir_spec(cache_general_dir, "0700"),
            _dir_spec(cache_image_dir, "0700"),
        ]

        resolved: Dict[str, Any] = {
            "files": {
                "configuration": _join(nginx_dir, "nginx.conf"),
            },
            "directories": {
                "configuration": {
                    "base": conf_dir,
                    "global": global_dir,
                    "servers": servers_dir,
                    "maps": maps_dir,
                    "streams": streams_dir,
                    "http_includes": [
                        global_dir,
                        maps_dir,
                        servers_http_dir,
                        servers_https_dir,
                    ],
                },
                "data": {
                    "www": www_dir,
                    "well_known": "/usr/share/nginx/well-known/",
                    "html": data_html_dir,
                    "files": data_files_dir,
                    "cdn": data_cdn_dir,
                    "global": data_global_dir,
                },
                "cache": {
                    "general": cache_general_dir,
                    "image": cache_image_dir,
                },
                "ensure": ensure,
                "ensure_paths": [d["path"] for d in ensure],
            },
        }

        if domain:
            protocol_override = kwargs.get("protocol", None)
            protocol = (
                _resolve_protocol_via_tls(
                    domain=domain,
                    variables=variables,
                    loader=getattr(self, "_loader", None),
                    templar=getattr(self, "_templar", None),
                )
                if not protocol_override
                else _normalize_protocol(protocol_override)
            )

            resolved["domain"] = {
                "name": domain,
                "protocol": protocol,
                "protocol_overridden": bool(protocol_override),
            }
            resolved["files"]["domain"] = _join(servers_dir, protocol, f"{domain}.conf")

        return [want_get(resolved, want)]
