"""Classify the result of `occ app:install` so the playbook can treat
version-incompatible plugins as warnings instead of failures.
"""

_INCOMPAT_MARKER = "is not compatible with this version of the server"
_ALREADY_MARKER = "already installed"
_UNAVAILABLE_MARKER = "was not found on the appstore"


def nextcloud_install_status(install_result):
    """Return status flags for a registered `occ app:install` shell result.

    Flags:
      - already      : plugin was already installed (no-op)
      - incompatible : plugin is not compatible with current Nextcloud version
      - unavailable  : plugin has no release on the appstore for this server
                       version (e.g. not yet ported); skippable, not fatal
      - ok           : success / already / incompatible — treat as terminal
                       (drives `until` and inverts to `failed_when`)
      - changed      : plugin was actually installed in this run
      - runnable     : plugin is available for enable/configure downstream
    """
    if not isinstance(install_result, dict):
        raise TypeError(
            "nextcloud_install_status expects a registered shell/command result dict"
        )

    rc = install_result.get("rc", -1)
    stdout = install_result.get("stdout") or ""
    stderr = install_result.get("stderr") or ""
    combined = stdout + stderr

    already = _ALREADY_MARKER in stdout
    incompatible = _INCOMPAT_MARKER in combined
    unavailable = _UNAVAILABLE_MARKER in combined
    success = rc == 0

    return {
        "already": already,
        "incompatible": incompatible,
        "unavailable": unavailable,
        "ok": success or already or incompatible,
        "changed": success and not already,
        "runnable": success or already,
    }


class FilterModule:
    def filters(self):
        return {"nextcloud_install_status": nextcloud_install_status}
