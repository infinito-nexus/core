"""Lookup ``openpost_relay_domains``: the names OpenPost's egress relay answers to.

Usage:

    {{ lookup('openpost_relay_domains') }}

Returns OpenPost's canonical domain, then the canonical domain of every sibling
under ``services.relay.siblings`` whose service flag is on, then the object
store's public domain when OpenPost uses one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

APPLICATION_ID = "web-app-openpost"
SIBLINGS_PATH = "services.relay.siblings"


def relay_domains(
    own_domain: str,
    siblings: Mapping[str, str],
    sibling_enabled: Callable[[str], Any],
    domain_of: Callable[[str], str],
    objstore_domain: str,
) -> list[str]:
    """Return the relay's names in alias order.

    Args:
        own_domain: OpenPost's canonical domain.
        siblings: service key to role id of every sibling the relay may carry.
        sibling_enabled: the service flag of a sibling's key.
        domain_of: the canonical domain of a role id.
        objstore_domain: the object store's public domain, "" without one.

    Returns:
        The own domain, the enabled siblings' domains, then the object store's.
    """
    domains = [own_domain]
    domains.extend(
        domain_of(role)
        for key, role in siblings.items()
        if boolean(sibling_enabled(key))
    )
    if objstore_domain:
        domains.append(objstore_domain)
    return domains


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if terms:
            raise AnsibleError("lookup('openpost_relay_domains') expects no terms.")

        def _lookup(name: str, *args: str) -> Any:
            plugin = lookup_loader.get(name, loader=self._loader, templar=self._templar)
            return plugin.run(list(args), variables=variables)[0]

        objstore_domain = (
            str(_lookup("objstore", APPLICATION_ID, "public_domain"))
            if boolean(_lookup("objstore", APPLICATION_ID, "enabled"))
            else ""
        )
        return [
            relay_domains(
                own_domain=str(_lookup("domain", APPLICATION_ID)),
                siblings=_lookup("config", APPLICATION_ID, SIBLINGS_PATH),
                sibling_enabled=lambda key: _lookup(
                    "config", APPLICATION_ID, f"services.{key}.enabled"
                ),
                domain_of=lambda role: str(_lookup("domain", role)),
                objstore_domain=objstore_domain,
            )
        ]
