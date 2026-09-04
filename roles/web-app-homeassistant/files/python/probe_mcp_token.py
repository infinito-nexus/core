# nocheck: mirrored-unit-test - the whole module is one authenticated GET against the
# running hub, issued at import from the container's own environment; there is no
# callable unit below it
"""Report whether the stored Home Assistant token still authenticates.

Environment:
    HA_PORT:  the hub's internal port.
    HA_TOKEN: the token to present.
"""

import os
import urllib.error
import urllib.request

TRANSIENT_STATUS = frozenset({429, 502, 503, 504})

req = urllib.request.Request(
    "http://localhost:" + os.environ["HA_PORT"] + "/api/",
    headers={"Authorization": "Bearer " + os.environ["HA_TOKEN"]},
)
try:
    with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - fixed http://localhost loopback of the hub
        print("ACCEPTED", response.status)
except urllib.error.HTTPError as err:
    marker = "PENDING" if err.code in TRANSIENT_STATUS else "REJECTED"
    raise SystemExit(f"{marker} {err.code}") from err
except OSError as err:
    raise SystemExit(f"PENDING unreachable: {err}") from err
