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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

WORKERS = 16


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


def _protocol_for(domain: str, default_protocol: str) -> str:
    """Onion services are plaintext-only (no TLS): probe them over http
    regardless of the clearnet default. Everything else uses the default."""
    return "http" if domain.endswith(".onion") else default_protocol


def _parse_json_mapping(name: str, value: str) -> dict[str, list[int]]:
    try:
        obj = json.loads(value)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--{name} must be a valid JSON string: {e}") from e
    if not isinstance(obj, dict):
        raise SystemExit(f"--{name} must be a JSON object (mapping)")
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


def _probe(domain: str, expected: list[int], web_protocol: str, verify) -> tuple:
    timeout = 30 if domain.endswith(".onion") else 10
    url = f"{_protocol_for(domain, web_protocol)}://{domain}"
    try:
        r = requests.head(url, allow_redirects=False, timeout=timeout, verify=verify)
    except requests.RequestException as e:
        return f"{domain}: error due to {e}", True
    if expected and r.status_code in expected:
        return f"{domain}: OK", False
    if not expected:
        return f"{domain}: ERROR: No expectations provided. Got {r.status_code}.", True
    return f"{domain}: ERROR: Expected {expected}. Got {r.status_code}.", True


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

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(
            pool.map(
                lambda d: _probe(d, expectations[d] or [], args.web_protocol, verify),
                sorted(expectations),
            )
        )
    for line, _ in results:
        print(line)
    errors = sum(failed for _, failed in results)

    if errors:
        print(f"Warning: {errors} domains responded with an unexpected status code.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
