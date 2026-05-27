# Returns the CDN path and URL structure for a given application_id as a single dict.
# Paths are at the top level; URLs are nested under the 'urls' key.
# The application_id is always resolved at call time — no scope dependency.
#
# API:
#   lookup('cdn', application_id)
#
# Returns a dict:
#   {
#     root, shared.{root,css,js,img,fonts}, vendor,
#     role.{id,root,version,release.{root,css,js,img,fonts}},
#     urls: <same structure with URLs instead of filesystem paths>
#   }
#
# Examples:
#   lookup('cdn', 'web-svc-cdn').shared.js          → filesystem path
#   lookup('cdn', 'web-svc-cdn').urls.shared.js     → URL
#   lookup('cdn', application_id).role.release.css  → role-specific filesystem path
#   lookup('cdn', application_id).urls.role.release.css → role-specific URL

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.tls_common import as_str


def _cdn_paths(cdn_root: str, application_id: str, version: str) -> dict:
    cdn_root = str(Path(cdn_root).resolve())
    return {
        "root": cdn_root,
        "shared": {
            "root": str(Path(cdn_root) / "_shared"),
            "css": str(Path(cdn_root) / "_shared" / "css"),
            "js": str(Path(cdn_root) / "_shared" / "js"),
            "img": str(Path(cdn_root) / "_shared" / "img"),
            "fonts": str(Path(cdn_root) / "_shared" / "fonts"),
        },
        "vendor": str(Path(cdn_root) / "vendor"),
        "role": {
            "id": application_id,
            "root": str(Path(cdn_root) / "roles" / application_id),
            "version": version,
            "release": {
                "root": str(Path(cdn_root) / "roles" / application_id / version),
                "css": str(Path(cdn_root) / "roles" / application_id / version / "css"),
                "js": str(Path(cdn_root) / "roles" / application_id / version / "js"),
                "img": str(Path(cdn_root) / "roles" / application_id / version / "img"),
                "fonts": str(
                    Path(cdn_root) / "roles" / application_id / version / "fonts"
                ),
            },
        },
    }


def _to_url_tree(obj: Any, cdn_root: str, base_url: str) -> Any:
    if isinstance(obj, dict):
        return {k: _to_url_tree(v, cdn_root, base_url) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_url_tree(v, cdn_root, base_url) for v in obj]
    if isinstance(obj, str):
        norm_root = str(Path(cdn_root).resolve())
        norm_val = str(Path(obj).resolve())
        if norm_val.startswith(norm_root):
            rel = os.path.relpath(norm_val, norm_root)
            rel_url = ("" if rel == "." else rel).replace(os.sep, "/")
            base = base_url.rstrip("/")
            return f"{base}/{rel_url}" if rel_url else f"{base}/"
        return obj
    return obj


class LookupModule(LookupBase):
    def run(self, terms, variables: dict | None = None, **kwargs):
        variables = variables or {}

        if not terms:
            raise AnsibleError("cdn: requires application_id as first argument")

        application_id = as_str(terms[0]).strip()
        if not application_id:
            raise AnsibleError("cdn: application_id must not be empty")

        nginx_lookup = lookup_loader.get(
            "nginx",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        )
        cdn_root = as_str(
            nginx_lookup.run(["directories.data.cdn"], variables=variables)[0]
        ).rstrip("/")

        tls_lookup = lookup_loader.get(
            "tls",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        )
        cdn_base_url = as_str(
            tls_lookup.run(["web-svc-cdn", "url.base"], variables=variables)[0]
        ).rstrip("/")

        paths = _cdn_paths(cdn_root, application_id, "latest")
        result = dict(paths)
        result["urls"] = _to_url_tree(paths, paths["root"], cdn_base_url)

        return [result]
