from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.design.branding import resolve_branding

ASSET_DIR = "design"


class LookupModule(LookupBase):
    """
    lookup('design', application_id)

    Returns the resolved corporate branding of one role:
      logo   absolute logo path, or False when the replacement is disabled
      title  title text, or False when the replacement is disabled
      name   role README H1
      label  title, else name (for installers that require a site name)
      slots  {name: {width, height, text_only}}
      domain canonical domain of the role
      dest   CDN directory the generated assets are written to
      urls   {"favicon": url, "<slot>": {"png": url, "svg": url}}
    """

    def _sub(self, name: str, terms: list, variables: dict[str, Any]) -> Any:
        plugin = lookup_loader.get(
            name,
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        )
        return plugin.run(terms, variables=variables)[0]

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        variables = variables or {}
        if len(terms) != 1:
            raise AnsibleError("design: expects exactly one application_id")
        application_id = str(terms[0]).strip()
        root = variables.get("playbook_dir")
        if not root:
            raise AnsibleError("design: 'playbook_dir' is unavailable")

        applications = self._sub("applications", [], variables)
        try:
            branding = resolve_branding(applications, application_id, Path(str(root)))
        except (KeyError, ValueError) as exc:
            raise AnsibleError(f"design: {exc}") from exc

        cdn = self._sub("cdn", [application_id], variables)
        base_url = f"{cdn['urls']['role']['release']['img'].rstrip('/')}/{ASSET_DIR}"
        urls: dict[str, Any] = {"favicon": f"{base_url}/favicon.ico"}
        for slot in branding["slots"]:
            urls[slot] = {
                "png": f"{base_url}/{slot}.png",
                "svg": f"{base_url}/{slot}.svg",
            }

        return [
            {
                **branding,
                "domain": self._sub("domain", [application_id], variables),
                "dest": str(Path(cdn["role"]["release"]["img"]) / ASSET_DIR),
                "urls": urls,
            }
        ]
