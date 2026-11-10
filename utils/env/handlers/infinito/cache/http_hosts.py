"""INFINITO_CACHE_HTTP_HOSTS: the hostnames the frontend serves without TLS.

An image build reaches the cache by hostname, but it cannot verify the
frontend's self-signed certificate unless its Dockerfile installs the CA, so
only these are safe to hijack for every build. A build that does install the
CA additionally gets the TLS hosts; `sys-svc-compose`'s override generator
decides that per image.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.hosts import HTTP_PORT, declarations

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_HTTP_HOSTS"
COMMENT = "Hostnames the cache frontend serves over plain HTTP; safe to hijack in any image build."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(
        KEY,
        ",".join(
            entry.host for entry in declarations().hosts if HTTP_PORT in entry.listen
        ),
        comment=COMMENT,
    )
