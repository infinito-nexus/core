"""Args:
    zone: the DNS name of the hosted zone, with or without its trailing dot.
    admin_access_key_id: the access key id of the AWS identity that reads it.
    admin_secret_access_key: its secret access key.

Returns:
    zone: the zone as given.
    zone_id: the id of the one Route 53 hosted zone of that exact name,
        without its ``/hostedzone/`` prefix; the module fails when none or
        more than one hosted zone holds the name.
"""

from __future__ import annotations

from ansible.module_utils.aws_api import AwsError, route53
from ansible.module_utils.basic import AnsibleModule

ARGUMENT_SPEC = {
    "zone": {"type": "str", "required": True},
    "admin_access_key_id": {"type": "str", "required": True, "no_log": True},
    "admin_secret_access_key": {"type": "str", "required": True, "no_log": True},
}
PATH = "/2013-04-01/hostedzonesbyname"
MAX_ITEMS = "100"
PREFIX = "/hostedzone/"


def _name(value: str) -> str:
    return str(value).lower().rstrip(".")


def hosted_zone(credentials: dict, zone: str) -> str:
    """Args:
        credentials: ``access_key_id`` and ``secret_access_key``.
        zone: the DNS name of the hosted zone.

    Returns:
        The id of the one hosted zone named ``zone``.

    Raises:
        LookupError: no or more than one hosted zone holds that name.
        AwsError: AWS refused the call.
    """
    if not _name(zone) or "*" in zone:
        raise LookupError(f"{zone!r} is no DNS name")
    root = route53(credentials, PATH, {"dnsname": zone, "maxitems": MAX_ITEMS})
    ids = [
        held.findtext("Id").removeprefix(PREFIX)
        for held in root.iterfind("HostedZones/HostedZone")
        if _name(held.findtext("Name")) == _name(zone)
    ]
    if len(ids) != 1:
        raise LookupError(
            f"Route 53 holds {len(ids)} hosted zones named {zone}, expected "
            f"exactly one: {ids}"
        )
    return ids[0]


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    credentials = {
        "access_key_id": module.params["admin_access_key_id"],
        "secret_access_key": module.params["admin_secret_access_key"],
    }
    try:
        zone_id = hosted_zone(credentials, module.params["zone"])
    except (AwsError, LookupError, OSError) as error:
        module.fail_json(msg=f"semaphore_route53_zone_info: {error}")
    module.exit_json(changed=False, zone=module.params["zone"], zone_id=zone_id)


if __name__ == "__main__":
    main()
