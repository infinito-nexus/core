from __future__ import annotations


def front_proxy_unserved(status, probes, stale_codes) -> list[str]:
    """Pick the vhosts OpenResty does not serve.

    Args:
        status: every probed vhost mapped to the status its probe ended on,
            -1 when it got no answer.
        probes: every queued vhost mapped to its probe, whose
            ``status_codes`` are the answers that prove the vhost is served.
        stale_codes: the answers of a vhost OpenResty has not loaded.

    Returns:
        The sorted vhosts whose status is a stale answer they do not accept.
    """
    stale = {int(code) for code in stale_codes}
    unserved = []
    for vhost, code in status.items():
        accepted = {int(accepted) for accepted in probes[vhost]["status_codes"]}
        if int(code) in stale and int(code) not in accepted:
            unserved.append(vhost)
    return sorted(unserved)


class FilterModule:
    def filters(self):
        return {"front_proxy_unserved": front_proxy_unserved}
