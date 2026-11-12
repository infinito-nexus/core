import json

_MARKER = "SOCIALLOGIN_ACCOUNTS "


def nextcloud_sociallogin_accounts(probe_result):
    """Name the accounts sociallogin holds under its own user ids.

    Args:
      probe_result: registered result of files/php/utils/sociallogin_accounts.php.
        Its stdout holds one ``SOCIALLOGIN_ACCOUNTS`` JSON line with the
        ``created`` user ids that carry sociallogin's account marker and the
        ``connected`` ``uid``/``identifier`` rows of ``sociallogin_connect``.

    Returns:
      Sorted labels, ``<uid> (created by sociallogin)`` or
      ``<uid> (connected to <identifier>)``; empty when sociallogin holds none.

    Raises:
      ValueError: stdout holds no single ``SOCIALLOGIN_ACCOUNTS`` line.
    """
    states = [
        json.loads(line[len(_MARKER) :])
        for line in (probe_result.get("stdout") or "").splitlines()
        if line.startswith(_MARKER)
    ]
    if len(states) != 1:
        raise ValueError(
            f"nextcloud_sociallogin_accounts expects one {_MARKER.strip()} line, "
            f"found {len(states)}"
        )
    return sorted(
        [f"{uid} (created by sociallogin)" for uid in states[0]["created"]]
        + [
            f"{row['uid']} (connected to {row['identifier']})"
            for row in states[0]["connected"]
        ]
    )


class FilterModule:
    def filters(self):
        return {"nextcloud_sociallogin_accounts": nextcloud_sociallogin_accounts}
