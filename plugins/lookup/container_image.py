"""Lookup `container_image`: compose ``image: "<ref>"`` line for a
container service.

Thin wrapper around the `image` lookup (the SPOT for resolving the
``<registry>/<image>:<version>`` reference). ``container_image`` only adds
the ``image: "..."`` compose-line wrapping so templates can drop it in as
a standalone statement:

    # roles/web-app-X/templates/compose.yml.j2
    {{ lookup('container_image', application_id, 'x') }}

    # Locally-built image (no registry upstream).
    {{ lookup('container_image', application_id, 'x', custom=True) }}

All resolution kwargs (``image=``, ``version=``, ``custom=``, ``tag_only=``)
are forwarded to `image`. For a bare reference (no wrapping), call the
`image` lookup directly.

Both terms (application_id, service_key) are required; they are validated
by `image`.
"""

from __future__ import annotations

from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        ref = lookup_loader.get(
            "image", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run(terms, variables=variables, **kwargs)[0]
        return [f'image: "{ref}"']
