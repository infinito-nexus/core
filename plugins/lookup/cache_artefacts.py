from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleLookupError
from ansible.plugins.lookup import LookupBase

from utils.cache.artefacts import records


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """
        Args:
            terms: role names to narrow to; none returns every artefact.
            variables: unused.
            kwargs: ``base``, the ``INFINITO_ARTEFACT_BASE`` each ``url`` is
                rewritten under; empty keeps the upstream.

        Returns:
            One mapping of artefact name to its record, ``upstream`` kept.

        Raises:
            AnsibleLookupError: a declaration breaks the manifest contract or
                the base is malformed; the message names role and artefact.
        """
        try:
            found = records(str(kwargs.get("base") or ""))
        except ValueError as exc:
            raise AnsibleLookupError(str(exc)) from exc
        roles = {str(term) for term in terms or []}
        return [
            {
                name: record
                for name, record in found.items()
                if not roles or record["role"] in roles
            }
        ]
