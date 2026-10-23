#!/usr/bin/env python3
"""
Ultra-thin checker: consume a JSON mapping of
{domain: {"codes": [...], "scheme": "http"|"https", "timeout": seconds}} and
verify HTTP HEAD responses. All mapping logic is done in the filters
`web_health_expectations` and `web_health_targets`.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Web health checker (expects precomputed per-domain targets)."
    )
    p.add_argument(
        "--targets",
        required=True,
        help='JSON STRING: {"domain": {"codes": [...], "scheme": "https", "timeout": 10}}',
    )
    return p.parse_args(argv)


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
        clean[domain] = {
            "codes": _codes(target.get("codes")),
            "scheme": scheme,
            "timeout": timeout,
        }
    return clean


def main(argv=None) -> int:
    args = parse_args(argv)
    targets = _parse_targets(args.targets)
    verify = True
    ca_trust_cert_host = os.environ.get("CA_TRUST_CERT_HOST", "").strip()
    if ca_trust_cert_host:
        if not Path(ca_trust_cert_host).is_file():
            print(
                f"CA_TRUST_CERT_HOST points to a missing certificate: {ca_trust_cert_host}"
            )
            return 1
        verify = ca_trust_cert_host

    errors = 0
    for domain in sorted(targets.keys()):
        target = targets[domain]
        expected = target["codes"]
        url = f"{target['scheme']}://{domain}"
        try:
            r = requests.head(
                url, allow_redirects=False, timeout=target["timeout"], verify=verify
            )
            if expected and r.status_code in expected:
                print(f"{domain}: OK")
            elif not expected:
                print(
                    f"{domain}: ERROR: No expectations provided. Got {r.status_code}."
                )
                errors += 1
            else:
                print(f"{domain}: ERROR: Expected {expected}. Got {r.status_code}.")
                errors += 1
        except requests.RequestException as e:
            print(f"{domain}: error due to {e}")
            errors += 1

    if errors:
        print(f"Warning: {errors} domains responded with an unexpected status code.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
