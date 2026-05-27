"""Resolve postgres-extension library install recipes.

Usage:
  {{ lookup('postgres_libraries', ['vector', 'bloom']) }}

Takes a list of extension names and returns the subset that needs a
custom library install on top of the postgis/postgis base image
(bloom, postgis, pg_trgm, unaccent are already in the base — those are
filtered out). Each returned entry is a dict with:
  - extension: the extension name (matches the SQL identifier)
  - name:      the library/source name (used in the Dockerfile context)
  - git_source: the upstream git repository to clone and build from
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

if TYPE_CHECKING:
    from collections.abc import Sequence


_REGISTRY: dict[str, dict[str, str]] = {
    "vector": {
        "name": "pgvector",
        "git_source": "https://github.com/pgvector/pgvector.git",
    },
}


class LookupModule(LookupBase):
    def run(
        self,
        terms: Sequence[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = list(terms or [])
        if len(terms) != 1:
            raise AnsibleError(
                "postgres_libraries: expected exactly one term — a list "
                "of extension names."
            )
        extensions = terms[0]
        if not isinstance(extensions, (list, tuple)):
            raise AnsibleError(
                "postgres_libraries: first term must be a list of extension names."
            )

        recipes: list[dict[str, str]] = []
        seen: set[str] = set()
        for ext in extensions:
            ext_name = str(ext).strip()
            if not ext_name or ext_name in seen:
                continue
            seen.add(ext_name)
            recipe = _REGISTRY.get(ext_name)
            if recipe is not None:
                recipes.append({"extension": ext_name, **recipe})

        return [recipes]
