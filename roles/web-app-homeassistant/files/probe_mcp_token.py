import os
import urllib.error
import urllib.request

req = urllib.request.Request(
    "http://localhost:" + os.environ["HA_PORT"] + "/api/",
    headers={"Authorization": "Bearer " + os.environ["HA_TOKEN"]},
)
try:
    with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - fixed http://localhost loopback of the hub
        print("ACCEPTED", response.status)
except urllib.error.HTTPError as err:
    raise SystemExit("REJECTED " + str(err.code)) from err
