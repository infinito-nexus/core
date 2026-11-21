from __future__ import annotations


def front_proxy_batch_culprits(vhosts, error) -> list[str]:
    """Args:
        vhosts: every vhost the front batch rendered, mapped to its record,
            whose ``consumer`` owns the vhost.
        error: the output of the ``openresty -t`` that refused the config.

    Returns:
        The sorted consumers whose vhost config file the error cites.
    """
    return sorted(
        {
            record["consumer"]
            for domain, record in vhosts.items()
            if f"/{domain}.conf" in str(error)
        }
    )


def front_proxy_batch_rechecks(vhosts) -> dict:
    """Args:
        vhosts: every vhost the front batch rendered, mapped to its record,
            whose ``changed`` tells whether its config changed and whose
            ``probe`` holds the ``url`` and the ``status_codes`` that prove
            it is served.

    Returns:
        The probe of every vhost whose config changed, by vhost.
    """
    return {
        domain: record["probe"]
        for domain, record in vhosts.items()
        if record["changed"]
    }


class FilterModule:
    def filters(self):
        return {
            "front_proxy_batch_culprits": front_proxy_batch_culprits,
            "front_proxy_batch_rechecks": front_proxy_batch_rechecks,
        }
