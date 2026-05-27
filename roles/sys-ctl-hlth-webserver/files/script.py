#!/usr/bin/env python3
"""
Ultra-thin checker: consume a JSON mapping of {domain: [expected_status_codes]}
and verify HTTP HEAD responses. All mapping logic is done in the filter
`web_health_expectations`.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Web health checker (expects precomputed domain→codes mapping)."
    )
    p.add_argument(
        "--web-protocol",
        default="https",
        choices=["http", "https"],
        help="Protocol to use",
    )
    p.add_argument(
        "--expectations", required=True, help='JSON STRING: {"domain": [codes], ...}'
    )
    return p.parse_args(argv)


def _parse_json_mapping(name: str, value: str) -> dict[str, list[int]]:
    try:
        obj = json.loads(value)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--{name} must be a valid JSON string: {e}") from e
    if not isinstance(obj, dict):
        raise SystemExit(f"--{name} must be a JSON object (mapping)")
    # sanitize list-of-ints shape
    clean = {}
    for k, v in obj.items():
        if isinstance(v, list):
            try:
                clean[k] = [int(x) for x in v]
            except Exception:
                clean[k] = []
        else:
            clean[k] = []
    return clean


def main(argv=None) -> int:
    args = parse_args(argv)
    expectations = _parse_json_mapping("expectations", args.expectations)
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
    for domain in sorted(expectations.keys()):
        expected = expectations[domain] or []
        url = f"{args.web_protocol}://{domain}"
        try:
            r = requests.head(url, allow_redirects=False, timeout=10, verify=verify)
            if expected and r.status_code in expected:
                print(f"{domain}: OK")
            elif not expected:
                # If somehow empty list slipped through, treat as failure to be explicit
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
        print(
            f"Warning: {errors} domains responded with an unexpected https status code."
        )
    return errors


if __name__ == "__main__":
    sys.exit(main())
