"""Role-local lookup plugin for web-app-fediwall.

    {{ lookup('fediwall_active', want_path) }}

For every Mastodon-API-compatible Fediverse sibling listed under the
SPOT ``meta/services.yml.fediwall.fediverse_siblings`` that is also
active on the current host (i.e. its application_id is in
``group_names``), return one entry per ``want_path``:

    siblings   -> the active sibling application_ids themselves
    domains    -> each sibling's primary domain (canonical[0])
    url_bases  -> each sibling's TLS ``url.base``
                  (= the same value ``lookup('tls', s, 'url.base')`` returns)

Used by:
    meta/server.yml                  -> connect-src CSP whitelist (url_bases)
    templates/wall-config.json.j2    -> default ``servers`` list   (domains)

Sharing one lookup keeps the active-set logic in a single SPOT and
mirrors the ``tls`` lookup's positional ``want`` API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_APPLICATION_ID = "web-app-fediwall"
_SIBLINGS_CONFIG_PATH = "services.fediwall.fediverse_siblings"
_VALID_WANTS = ("siblings", "domains", "url_bases")


def select_active(
    siblings: Iterable[str] | None,
    group_names: Iterable[str] | None,
) -> list[str]:
    """Return the subset of `siblings` whose names appear in `group_names`.

    Order of `siblings` is preserved. Duplicates in `siblings` are
    preserved as-is. ``None`` inputs are treated as empty.
    """
    if not siblings:
        return []
    active = set(group_names or [])
    return [s for s in siblings if s in active]


def resolve_for_want(
    siblings: Iterable[str] | None,
    group_names: Iterable[str] | None,
    want: str,
    resolver: Callable[[str], str] | None,
) -> list[str]:
    """Return one value per active sibling, depending on `want`.

    For ``want == 'siblings'`` the active sibling names themselves are
    returned (no resolver call). For ``'domains'`` and ``'url_bases'``
    the caller-supplied `resolver(sibling)` produces the value.
    """
    if want == "siblings":
        return select_active(siblings, group_names)
    if want not in _VALID_WANTS:
        raise AnsibleError(
            f"fediwall_active: want must be one of {_VALID_WANTS}, got '{want}'"
        )
    if resolver is None:
        raise AnsibleError(f"fediwall_active: want='{want}' requires a resolver")
    return [resolver(s) for s in select_active(siblings, group_names)]


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                f"fediwall_active: exactly one positional argument required "
                f"(want, one of {_VALID_WANTS})"
            )

        want = str(terms[0]).strip()
        if want not in _VALID_WANTS:
            raise AnsibleError(
                f"fediwall_active: want must be one of {_VALID_WANTS}, got '{want}'"
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        group_names = variables.get("group_names", []) or []

        config_lookup = lookup_loader.get(
            "config", loader=self._loader, templar=self._templar
        )
        siblings = (
            config_lookup.run(
                [_APPLICATION_ID, _SIBLINGS_CONFIG_PATH], variables=variables
            )[0]
            or []
        )

        if want == "siblings":
            return [select_active(siblings, group_names)]

        tls_lookup = lookup_loader.get(
            "tls", loader=self._loader, templar=self._templar
        )

        if want == "domains":

            def _resolve_domain(sibling: str) -> str:
                return str(
                    tls_lookup.run([sibling, "domain"], variables=variables)[0]
                ).strip()

            return [resolve_for_want(siblings, group_names, want, _resolve_domain)]

        def _resolve_url_base(sibling: str) -> str:
            return str(
                tls_lookup.run([sibling, "url.base"], variables=variables)[0]
            ).strip()

        return [resolve_for_want(siblings, group_names, want, _resolve_url_base)]
