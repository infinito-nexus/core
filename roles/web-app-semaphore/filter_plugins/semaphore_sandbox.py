from __future__ import annotations

from typing import Any

PROBES = 2
BLIND_READS = ("token", "marker")
BLIND_FLAGS = {
    "child_alive": "lost its child",
    "child_mem": "read no memory of its child",
    "ipc_seen": "left no IPC object to see",
}


def semaphore_sandbox_findings(report: dict[str, Any]) -> list[str]:
    """Args:
    report: the stdout of ``sandbox/probe.py check`` as JSON: ``inside``
        holds the reports of the probes that ran at once, each in a sandbox
        of its own, ``outside`` those that ran as the runner uid outside
        any; each report carries ``reads``, ``exit`` and ``child_alive``,
        a sandboxed one ``ipc_left``, an unsandboxed one ``child_mem`` and
        ``ipc_seen``.

    Returns:
        Every read a sandboxed probe reported, every child or IPC object of
        one that outlived its sandbox and every probe that did not report;
        when an outside probe missed the token, the other marker, the memory
        of its child, its IPC object or its surviving child, the check is
        blind and that is a finding too.
    """
    inside = report.get("inside") or []
    outside = report.get("outside") or []
    findings = [
        f"{len(probes)} {where} probes reported, not {PROBES}"
        for where, probes in (("sandboxed", inside), ("unsandboxed", outside))
        if len(probes) != PROBES
    ]
    for number, probe in enumerate(inside, 1):
        if probe.get("exit") != 0 or "reads" not in probe:
            findings.append(f"sandboxed probe {number} ended {probe.get('exit')}")
        findings += [
            f"the sandbox of probe {number} allowed {read}"
            for read in probe.get("reads", [])
        ]
        if probe.get("child_alive", True):
            findings.append(f"a child of probe {number} outlived its sandbox")
        if probe.get("ipc_left", True):
            findings.append(f"an IPC object of probe {number} outlived its sandbox")
    for number, probe in enumerate(outside, 1):
        reads = probe.get("reads", [])
        findings += [
            f"the check is blind: unsandboxed probe {number} missed the {read}"
            for read in BLIND_READS
            if read not in reads
        ]
        findings += [
            f"the check is blind: unsandboxed probe {number} {what}"
            for key, what in BLIND_FLAGS.items()
            if not probe.get(key, False)
        ]
    return findings


class FilterModule:
    def filters(self):
        return {"semaphore_sandbox_findings": semaphore_sandbox_findings}
