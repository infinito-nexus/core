from __future__ import annotations

from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class _SharedVariables(dict):
    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        return dict(self)


class LookupModule(LookupBase):
    def run(
        self, terms: list[Any], variables: dict[str, Any], **kwargs: Any
    ) -> list[Any]:
        """
        Args:
            terms: the template paths, resolved like ``ansible.builtin.template``.
            variables: the caller's variables; every term renders over a fresh
                top-level copy whose values are shared with the caller.
            kwargs: the ``ansible.builtin.template`` options, such as
                ``template_vars``.

        Returns:
            One rendered string per term.
        """
        template = lookup_loader.get(
            "template", loader=self._loader, templar=self._templar
        )
        return template.run(terms, variables=_SharedVariables(variables), **kwargs)
