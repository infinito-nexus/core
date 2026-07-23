# Central onion-aware base-URL resolver.
#
# `lookup('canonical_url', application_id[, canonical_key])` returns the web
# base URL (``scheme://host``, no trailing slash) for an application, or for a
# specific named canonical (e.g. ``element`` / ``synapse`` / ``filer``) when the
# role declares ``server.domains.canonical`` as a dict.
#
# The scheme follows the resolved domain: ``.onion`` targets are plaintext (Tor
# provides the encryption) so they resolve to ``http``; everything else follows
# the deployment TLS setting (``https`` when enabled). Because the domain comes
# from the onion-injected merged-domain map, an app deployed onion-exclusive
# yields its ``.onion`` URL automatically — callers never branch on
# clearnet-vs-onion themselves.
#
# `consumer=<application_id>` gates the result on the consumer's service
# binding: it returns '' unless ``services.<target entity>.enabled`` is truthy
# on the consuming application. This replaces the recurring
# ``(lookup(...) if lookup('config', application_id, 'services.X.enabled') else '')``
# template branching.
#
# Primary resolution is family-aligned: a clearnet-primary consumer (via
# ``consumer=`` or the caller's ``application_id``) referencing an
# onion-primary target gets the target's clearnet sibling when one exists.

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.domains.primary_domain import get_primary_domain
from utils.roles.entity.name import get_entity_name
from utils.tls_common import (
    align_domain_to_consumer,
    as_str,
    require,
    resolve_enabled,
)


class LookupModule(LookupBase):
    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        variables = variables or {}

        if not terms or len(terms) not in (1, 2):
            raise AnsibleError(
                "canonical_url: one or two terms required: "
                "(application_id[, canonical_key])"
            )

        templar = getattr(self, "_templar", None)
        app_id = as_str(templar.template(terms[0]) if templar else terms[0])
        if not app_id:
            raise AnsibleError("canonical_url: application_id is empty")
        key = as_str(terms[1]).strip() if len(terms) == 2 else ""

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=variables, roles_dir=kwargs.get("roles_dir"))[0]

        consumer = as_str(
            templar.template(kwargs["consumer"])
            if templar and "consumer" in kwargs
            else kwargs.get("consumer", "")
        )
        if consumer:
            consumer_app = applications.get(consumer, {})
            if not isinstance(consumer_app, dict):
                consumer_app = {}
            binding = consumer_app.get("services", {}).get(get_entity_name(app_id), {})
            if not (isinstance(binding, dict) and binding.get("enabled")):
                return [""]

        domains = lookup_loader.get(
            "domains", loader=self._loader, templar=templar
        ).run([], variables=variables, roles_dir=kwargs.get("roles_dir"))[0]

        if key:
            app_domains = domains.get(app_id)
            if not isinstance(app_domains, dict):
                raise AnsibleError(
                    f"canonical_url: '{app_id}' has no named-canonical domains; "
                    f"cannot resolve key '{key}'"
                )
            domain = app_domains.get(key)
            if not isinstance(domain, str) or not domain:
                raise AnsibleError(
                    f"canonical_url: '{app_id}' has no canonical '{key}' "
                    f"(available: {sorted(app_domains)})"
                )
        else:
            domain = get_primary_domain(domains, app_id)
            domain = align_domain_to_consumer(
                domains,
                app_id,
                domain,
                consumer=consumer,
                variables=variables,
                templar=templar,
            )

        app = applications.get(app_id, {})
        if not isinstance(app, dict):
            app = {}

        enabled_default = require(variables, "TLS_ENABLED", (bool, int))
        enabled = resolve_enabled(app, bool(enabled_default), primary_domain=domain)
        scheme = "https" if enabled else "http"
        return [f"{scheme}://{domain}"]
