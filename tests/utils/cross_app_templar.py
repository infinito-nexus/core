from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from utils.cache.applications import get_lazy_applications

if TYPE_CHECKING:
    from pathlib import Path

_REFERENCE = re.compile(r"\{\{\s*ref\s+(\S+)\s+(\S+)\s*\}\}")
_VARIABLE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class CrossAppTemplar:
    """
    Args:
        roles_dir: the roles tree the references read.
        available_variables: the templar's own variables.

    Attributes:
        rendered: every ``(application_id, text)`` pair passed to
            ``template``, in call order.
    """

    def __init__(
        self, roles_dir: Path, available_variables: dict[str, Any] | None = None
    ) -> None:
        self.available_variables: dict[str, Any] = dict(available_variables or {})
        self.rendered: list[tuple[str, str]] = []
        self._roles_dir = roles_dir

    def template(self, value: Any, **_kwargs: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = str(value)
        scope = self.available_variables
        self.rendered.append((str(scope.get("application_id")), text))
        reference = _REFERENCE.fullmatch(text.strip())
        if reference is None:
            return _VARIABLE.sub(lambda match: str(scope[match.group(1)]), text)
        node = get_lazy_applications(
            variables=scope, roles_dir=self._roles_dir, templar=self
        )[reference.group(1)]
        for part in reference.group(2).split("."):
            node = node[part]
        return self.template(node)
