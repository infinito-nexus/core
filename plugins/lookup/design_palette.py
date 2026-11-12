from __future__ import annotations

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.design.palette import build_palette


class LookupModule(LookupBase):
    """
    Return the corporate design palette for one base color.

    Usage:
      {{ lookup('design_palette', '#001f3f') }}
      -> {"scale": {...}, "light": {...}, "dark": {...}}

    Each mapping is keyed by CSS custom property name (``--design-*``) and
    carries a ``<name>-rgb`` triplet for every color.
    """

    def run(self, terms, variables=None, **kwargs):
        if len(terms) != 1:
            raise AnsibleError("design_palette: expects exactly one base color")
        try:
            return [build_palette(terms[0])]
        except ValueError as exc:
            raise AnsibleError(f"design_palette: {exc}") from exc
