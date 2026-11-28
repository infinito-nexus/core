#!/usr/bin/env python3
"""
Ultra-thin checker: consume a JSON mapping of
{domain: {"codes": [...], "scheme": "http"|"https", "timeout": seconds,
"paused_marker": path, "application_id": id}} and verify HTTP HEAD responses.
All mapping logic is done in the filters `web_health_expectations` and
`web_health_targets`; a domain whose app-control marker reads ``stopped`` also
accepts the 503 of the paused page.

After every sweep it writes the status document
{"generated": iso, "applications": {id: {"state", "checked"}}} to
``--status-file``, limited to the ids of ``--status-applications``; ``state``
is ``running``, ``paused``, ``degraded`` or ``down``, and an application with
several domains takes its worst one. A listed id without any target, such as
a card without a domain, gets no entry and a ``NO TARGET`` line, so its badge
reads unknown on purpose.
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import requests

WORKERS = 16
PAUSED_STATUS = 503
SERVER_ERROR = 500
SEVERITY = {"running": 0, "paused": 1, "degraded": 2, "down": 3}


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Web health checker (expects precomputed per-domain targets)."
    )
    p.add_argument(
        "--targets",
        required=True,
        help='JSON STRING: {"domain": {"codes": [...], "scheme": "https", "timeout": 10}}',
    )
    p.add_argument(
        "--status-file",
        required=True,
        help="path of the status document the dashboard reads",
    )
    p.add_argument(
        "--status-applications",
        required=True,
        help="JSON STRING: list of the application ids the status document may name",
    )
    return p.parse_args(argv)


def _parse_applications(value: str) -> frozenset[str]:
    try:
        ids = json.loads(value)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--status-applications must be valid JSON: {e}") from e
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise SystemExit("--status-applications must be a JSON list of strings")
    return frozenset(ids)


def _codes(value) -> list[int]:
    if not isinstance(value, list):
        return []
    try:
        return [int(x) for x in value]
    except (TypeError, ValueError):
        return []


def _parse_targets(value: str) -> dict[str, dict]:
    try:
        obj = json.loads(value)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--targets must be a valid JSON string: {e}") from e
    if not isinstance(obj, dict):
        raise SystemExit("--targets must be a JSON object (mapping)")
    clean = {}
    for domain, target in obj.items():
        if not isinstance(target, dict):
            raise SystemExit(f"--targets entry for {domain} must be a mapping")
        scheme = target.get("scheme")
        if scheme not in ("http", "https"):
            raise SystemExit(f"--targets entry for {domain} has scheme {scheme!r}")
        timeout = target.get("timeout")
        if not isinstance(timeout, int) or timeout <= 0:
            raise SystemExit(f"--targets entry for {domain} has timeout {timeout!r}")
        paused_marker = target.get("paused_marker")
        if not isinstance(paused_marker, str):
            raise SystemExit(
                f"--targets entry for {domain} has paused_marker {paused_marker!r}"
            )
        application_id = target.get("application_id")
        if not isinstance(application_id, str):
            raise SystemExit(
                f"--targets entry for {domain} has application_id {application_id!r}"
            )
        clean[domain] = {
            "codes": _codes(target.get("codes")),
            "scheme": scheme,
            "timeout": timeout,
            "paused_marker": paused_marker,
            "application_id": application_id,
        }
    return clean


def _paused(marker: str) -> bool:
    """Return whether app-control paused the application behind a domain.

    Args:
        marker: path of its app-control state marker, empty outside app control.
    """
    if not marker or not Path(marker).is_file():
        return False
    return Path(marker).read_text(encoding="utf-8").strip() == "stopped"


def _probe(domain: str, target: dict, verify) -> tuple[str, bool, str, int | None]:
    """Probe one domain and report its line, whether it failed, its state and code.

    Args:
        domain: the host to probe.
        target: its ``codes``, ``scheme``, ``timeout`` and ``paused_marker``.
        verify: what ``requests`` verifies the certificate against.
    """
    expected = target["codes"]
    paused = _paused(target["paused_marker"])
    if expected and paused:
        expected = [*expected, PAUSED_STATUS]
    url = f"{target['scheme']}://{domain}"
    try:
        r = requests.head(
            url, allow_redirects=False, timeout=target["timeout"], verify=verify
        )
    except requests.RequestException as e:
        return f"{domain}: error due to {e}", True, "paused" if paused else "down", None
    code = r.status_code
    if paused:
        state = "paused"
    elif code >= SERVER_ERROR:
        state = "down"
    else:
        state = "running" if code in expected else "degraded"
    if expected and code in expected:
        return f"{domain}: OK", False, state, code
    if not expected:
        return (
            f"{domain}: ERROR: No expectations provided. Got {code}.",
            True,
            state,
            code,
        )
    return f"{domain}: ERROR: Expected {expected}. Got {code}.", True, state, code


def status_document(
    targets: dict, results: list, now: str, published: frozenset[str]
) -> dict:
    """Return the per-application status document of one sweep.

    Args:
        targets: the parsed targets, keyed by domain.
        results: ``_probe`` results in the sorted order of ``targets``.
        now: ISO 8601 time of the sweep.
        published: the application ids the document may name.
    """
    states = {}
    for domain, (_, _, state, _) in zip(sorted(targets), results, strict=True):
        application_id = targets[domain]["application_id"]
        if application_id not in published:
            continue
        known = states.get(application_id)
        if known is None or SEVERITY[state] > SEVERITY[known["state"]]:
            states[application_id] = {"state": state, "checked": now}
    return {"generated": now, "applications": states}


def write_status(path: Path, document: dict) -> None:
    """Replace the status document atomically so a reader never sees half of it.

    Args:
        path: the status file.
        document: output of ``status_document``.
    """
    pending = path.with_name(f"{path.name}.tmp")
    pending.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", "utf-8")
    pending.chmod(0o644)
    pending.replace(path)


def main(argv=None) -> int:
    args = parse_args(argv)
    targets = _parse_targets(args.targets)
    published = _parse_applications(args.status_applications)
    verify = True
    ca_trust_bundle = os.environ.get("CA_TRUST_BUNDLE", "").strip()
    if ca_trust_bundle:
        if not Path(ca_trust_bundle).is_file():
            print(f"CA_TRUST_BUNDLE points to a missing bundle: {ca_trust_bundle}")
            return 1
        verify = ca_trust_bundle

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(
            pool.map(
                lambda d: _probe(d, targets[d], verify),
                sorted(targets),
            )
        )
    for line, *_ in results:
        print(line)
    probed = {target["application_id"] for target in targets.values()}
    for application_id in sorted(published - probed):
        print(f"{application_id}: NO TARGET: its dashboard badge reads unknown.")
    errors = sum(failed for _, failed, *_ in results)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    write_status(
        Path(args.status_file), status_document(targets, results, now, published)
    )

    if errors:
        print(f"Warning: {errors} domains responded with an unexpected status code.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
