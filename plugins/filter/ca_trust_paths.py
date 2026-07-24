"""Filter ``ca_cert_host``: SPOT for the host-side root-CA cert location.

    {{ SOFTWARE_DOMAIN | ca_cert_host }}  -> /etc/<software_domain>/ca/root-ca.crt

``ca_cert_host`` is where sys-ca-selfsigned provisions the root CA on the host.
The container-side bind-mount targets live in the ``CA_TRUST`` group_vars SPOT
(``inject_cert_container`` / ``inject_wrapper_container``) and reach the
standalone runtime scripts as env vars and CLI arguments.
"""

from __future__ import annotations


def ca_cert_host(software_domain: str) -> str:
    return f"/etc/{software_domain}/ca/root-ca.crt"


class FilterModule:
    def filters(self):
        return {"ca_cert_host": ca_cert_host}
