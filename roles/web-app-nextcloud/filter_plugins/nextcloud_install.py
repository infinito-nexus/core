"""Classify the result of `occ app:install` so the playbook can treat
version-incompatible plugins as warnings instead of failures, and gate and
join an `occ app:install` that runs in the background.
"""

import json
import re

_INCOMPAT_MARKER = "is not compatible with this version of the server"
_ENABLED_LINE = re.compile(r"^\S+ enabled$", re.MULTILINE)
_ALREADY_MARKER = "already installed"
_UNAVAILABLE_MARKER = "was not found on the appstore"
_TRANSPORT_MARKERS = ("cURL error", "ConnectException")
_TIMEOUT_RC = 124
_SIGNAL_RCS = range(129, 193)
_MIGRATION_STATE_MARKER = "MIGRATION_STATE "
_JOB_FILE_GRACE_ATTEMPTS = 15


def nextcloud_install_status(install_result):
    """Return status flags for a registered `occ app:install` shell result.

    Flags:
      - already      : plugin was already installed (no-op)
      - incompatible : plugin is not compatible with current Nextcloud version
      - unavailable  : plugin has no release on the appstore for this server
                       version (e.g. not yet ported); skippable, not fatal.
                       Only claimed when the catalogue was actually read: occ
                       prints the same sentence when the fetch itself failed,
                       and a plugin the deploy could not reach is not a plugin
                       the appstore does not carry
      - ok           : success / already / incompatible — treat as terminal
                       (drives `until` and inverts to `failed_when`)
      - changed      : plugin was actually installed in this run
      - runnable     : plugin is available for enable/configure downstream
      - enabled      : the install enabled the plugin too; its stdout holds
                       an ``<app> enabled`` line
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
    transport_failed = any(marker in combined for marker in _TRANSPORT_MARKERS)
    unavailable = _UNAVAILABLE_MARKER in combined and not transport_failed
    success = rc == 0

    return {
        "already": already,
        "incompatible": incompatible,
        "unavailable": unavailable,
        "ok": success or already or incompatible,
        "changed": success and not already,
        "runnable": success or already,
        "enabled": success and _ENABLED_LINE.search(stdout) is not None,
    }


def nextcloud_background_gate(gate_result):
    """Decide whether other occ calls may run next to a background `occ app:install`.

    Args:
      gate_result: registered result of the gate shell, polled in an
        ``until`` loop so it carries ``attempts``. Its first stdout line is
        the async job file of the install (one JSON object, holding
        ``started`` while the job runs and the module result once it ended,
        empty until async_wrapper wrote it); a later line holds the
        ``MIGRATION_STATE`` JSON that files/php/utils/migration_state.php
        prints with the ``migrated`` and ``available`` versions of the app.

    Returns:
      'open'   - the job ended with an occ exit code, or the schema of the app
                 is in place: at least one migration lies on disk and the
                 versions on disk are exactly the versions recorded in
                 oc_migrations
      'killed' - the job ended without an occ exit code (see
                 ``nextcloud_background_lost``), or its job file is still
                 missing after the grace attempts
      'wait'   - neither yet
    """
    if not isinstance(gate_result, dict):
        raise TypeError(
            "nextcloud_background_gate expects a registered shell/command result dict"
        )

    lines = (gate_result.get("stdout") or "").splitlines()
    if not lines or not lines[0].strip():
        return (
            "wait" if gate_result["attempts"] <= _JOB_FILE_GRACE_ATTEMPTS else "killed"
        )
    job = json.loads(lines[0])
    if not isinstance(job, dict):
        raise TypeError(
            "nextcloud_background_gate expects the async job file on the first stdout line"
        )
    if "started" not in job:
        return "killed" if nextcloud_background_lost(job) else "open"

    if gate_result.get("rc") != 0:
        return "wait"
    states = [
        json.loads(line[len(_MIGRATION_STATE_MARKER) :])
        for line in lines[1:]
        if line.startswith(_MIGRATION_STATE_MARKER)
    ]
    if len(states) != 1:
        return "wait"
    available = set(states[0]["available"])
    settled = bool(available) and available == set(states[0]["migrated"])
    return "open" if settled else "wait"


def nextcloud_background_lost(job_result):
    """Tell whether a background `occ app:install` ended without an occ exit code.

    Args:
      job_result: `async_status` result or async job file content of the
        background install.

    Returns:
      True when the job carries no exit code (still running, killed by the
      async timeout, crashed), a signal killed its shell (negative code), a
      timeout killed its exec (124) or a signal ended the exec (129-192, 137
      for the KILL after the timeout).
    """
    if not isinstance(job_result, dict):
        raise TypeError(
            "nextcloud_background_lost expects a registered async_status result dict"
        )
    rc = job_result.get("rc")
    return rc is None or rc < 0 or rc == _TIMEOUT_RC or rc in _SIGNAL_RCS


class FilterModule:
    def filters(self):
        return {
            "nextcloud_install_status": nextcloud_install_status,
            "nextcloud_background_gate": nextcloud_background_gate,
            "nextcloud_background_lost": nextcloud_background_lost,
        }
