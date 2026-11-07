"""Lookup ``litellm_api_key``: the virtual key a consumer presents to the gateway.

    "{{ lookup('litellm_api_key', application_id) }}"

Beside its own gateway a consumer presents the key the gateway minted for it,
``secrets.credentials.litellm_api_key`` of the consumer. On a host whose
``svc-ai-litellm`` names another host's gateway in
``services.litellm.gateway_host``, every consumer presents the one key that
gateway registered for this host, ``secrets.credentials.gateway_key`` of
``svc-ai-litellm``, because the gateway mints no key per consumer of another
host. Deciding that here keeps the branch out of every consumer role.

A consumer that holds no key yields ``''``, which the gateway's consumer
contract refuses by name, rather than an error that names only a path.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

GATEWAY_ROLE = "svc-ai-litellm"
GATEWAY_HOST_PATH = "services.litellm.gateway_host"
HOST_KEY_PATH = "secrets.credentials.gateway_key"
CONSUMER_KEY_PATH = "secrets.credentials.litellm_api_key"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = list(terms or [])
        if len(terms) != 1 or not str(terms[0]).strip():
            raise AnsibleError(
                "litellm_api_key: expected the consumer's application_id, "
                "e.g. lookup('litellm_api_key', application_id)"
            )
        application_id = str(terms[0]).strip()
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        config = lookup_loader.get(
            "config", loader=self._loader, templar=getattr(self, "_templar", None)
        )
        gateway_host = config.run([GATEWAY_ROLE, GATEWAY_HOST_PATH], variables=vars_)[0]
        if str(gateway_host or "").strip():
            return [config.run([GATEWAY_ROLE, HOST_KEY_PATH], variables=vars_)[0]]
        return [config.run([application_id, CONSUMER_KEY_PATH, ""], variables=vars_)[0]]
