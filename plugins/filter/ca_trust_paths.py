"""Filter ``ca_cert_host`` plus the container-side CA constant: SPOT for the root-CA cert locations.

    {{ SOFTWARE_DOMAIN | ca_cert_host }}  -> /etc/<software_domain>/ca/root-ca.crt

``ca_cert_host`` is where sys-ca-selfsigned provisions the root CA on the host.
``CA_CONTAINER_CERT`` is the bind-mount target sys-svc-compose-ca/sys-svc-container
inject into every container; the standalone runtime scripts
(roles/sys-svc-compose-ca/files/compose_ca.py, roles/sys-svc-container/files/container.py)
cannot import this module and carry the literal themselves; the unit test pins
them to this SPOT.
"""

from __future__ import annotations

CA_CONTAINER_CERT = "/tmp/infinito/ca/root-ca.crt"  # noqa: S108 - fixed bind-mount target inside containers, not a writable temp file


def ca_cert_host(software_domain: str) -> str:
    return f"/etc/{software_domain}/ca/root-ca.crt"


class FilterModule:
    def filters(self):
        return {"ca_cert_host": ca_cert_host}
