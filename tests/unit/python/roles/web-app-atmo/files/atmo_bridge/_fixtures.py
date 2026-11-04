import importlib
import sys

from . import PROJECT_ROOT

PYTHON_DIR = PROJECT_ROOT / "roles" / "web-app-atmo" / "files" / "python"
DID = "did:plc:alice"
APPVIEW = "https://rsvp.example.org"
ENV = {
    "BRIDGE_PDS_URL": "https://pds.example.org/",
    "BRIDGE_APPVIEW_URL": "https://rsvp.example.org/",
    "BRIDGE_MOBILIZON_URL": "https://event.example.org",
    "BRIDGE_MOBILIZON_EMAIL": "admin@example.org",
    "BRIDGE_MOBILIZON_PASSWORD": "pw",
    "BRIDGE_STATE_PATH": "/var/lib/atmo-bridge/state.sqlite",
    "BRIDGE_INTERVAL_SECONDS": "60",
}


def make_importable() -> None:
    if str(PYTHON_DIR) not in sys.path:
        sys.path.insert(0, str(PYTHON_DIR))


def load(module: str):
    """Import one module of the role's shipped ``atmo_bridge`` package.

    Args:
        module: name of the module inside ``atmo_bridge``.

    Returns:
        The imported module.
    """
    make_importable()
    return importlib.import_module(f"atmo_bridge.{module}")


mapping = load("mapping")


def _uri(rkey):
    return f"at://{DID}/{mapping.EVENT_COLLECTION}/{rkey}"


def _record(**overrides):
    record = {
        "$type": mapping.EVENT_COLLECTION,
        "name": "Beaver meetup",
        "description": "Bring wood.\n\nAnd <snacks>.",
        "createdAt": "2026-10-01T10:00:00Z",
        "startsAt": "2026-11-05T18:00:00+01:00",
        "endsAt": "2026-11-05T21:00:00+01:00",
        "status": f"{mapping.TOKEN_PREFIX}scheduled",
        "mode": f"{mapping.TOKEN_PREFIX}inperson",
        "locations": [
            {
                "$type": mapping.ADDRESS_LOCATION,
                "street": "Damm 1",
                "locality": "Berlin",
                "postalCode": "10115",
                "country": "DE",
                "name": "The lodge",
            },
            {
                "$type": "community.lexicon.location.geo",
                "latitude": "52.52",
                "longitude": "13.40",
            },
        ],
        "uris": [{"uri": "https://beavers.example.org/meetup"}],
    }
    record.update(overrides)
    return record
