#!/usr/bin/env python3
"""Interrogate the deployed package cache through its own containers.

Every assertion is made against the running stack: Nexus is asked for each
declared repository, the frontend is asked for the certificates it serves,
and each cached hostname is requested through the frontend exactly as a
package manager would. A declaration the deploy did not realise therefore
fails here rather than passing on the strength of the file that declared it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

NEXUS = os.environ["CACHE_PACKAGE_TEST_CONTAINER"]
FRONTEND = os.environ["CACHE_PACKAGE_TEST_FRONTEND"]
PORT = os.environ["CACHE_PACKAGE_TEST_PORT"]
CERTS_DIR = os.environ["CACHE_PACKAGE_TEST_CERTS_DIR"]
REPOS = json.loads(os.environ["CACHE_PACKAGE_TEST_REPOS"])
HOSTS = json.loads(os.environ["CACHE_PACKAGE_TEST_HOSTS"])
MARKER = os.environ["CACHE_PACKAGE_TEST_BACKEND_MARKER"]

NO_HEADER = "-"
NEXUS_IO_FAILURE = "502"
TIMEOUT = 60

failures: list[str] = []


def run(container: str, argv: list[str]) -> tuple[int, str]:
    """Return the exit status and stdout of *argv* inside *container*.

    Args:
        container: the container to run in.
        argv: the command and its arguments.
    """
    done = subprocess.run(
        ["container", "exec", container, *argv],
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
    )
    return done.returncode, done.stdout.strip()


def status(container: str, url: str, host: str = "") -> str:
    """Return the HTTP status *url* answers with, as seen from *container*."""
    argv = [
        "curl",
        "-sS",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "-k",
        "--max-time",
        "30",
    ]
    if host:
        argv += ["-H", f"Host: {host}"]
    code, out = run(container, [*argv, url])
    return out if code == 0 else ""


def response_head(container: str, url: str, host: str) -> str:
    """Return the response header block *url* answers with through *container*.

    Args:
        container: the container to send the request from.
        url: the URL to request.
        host: the Host header to send.
    """
    argv = [
        "curl",
        "-sS",
        "-o",
        "/dev/null",
        "-D",
        "-",
        "-k",
        "--max-time",
        "30",
        "-H",
        f"Host: {host}",
        url,
    ]
    _, out = run(container, argv)
    return out


def parse_head(head: str) -> tuple[str, dict[str, str]]:
    """Return the status code and headers of the last response in *head*.

    Args:
        head: what ``curl -D -`` printed, interim ``1xx`` responses first.

    Returns:
        The status code, empty when no status line arrived, and the headers
        keyed by their lower-cased name.
    """
    code, headers = "", {}
    for raw in head.splitlines():
        line = raw.strip()
        if line.startswith("HTTP/"):
            parts = line.split()
            code, headers = (parts[1] if len(parts) > 1 else ""), {}
        elif ":" in line:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
    return code, headers


def nexus_answered(timing: str) -> bool:
    """Whether nginx parsed a response header from Nexus on its final attempt.

    Args:
        timing: nginx's ``$upstream_header_time`` as the marker carries it:
            one entry per attempt, ``,`` between peers and `` : `` across an
            internal redirect such as the mirror fallback, ``-`` for an
            attempt that got no header, empty when nginx never proxied.
    """
    last = re.split(r"[,:]", timing)[-1].strip()
    return last not in {"", NO_HEADER}


def proxied_verdict(target: str, repo: str, head: str, marker: str) -> str:
    """Return why *head* shows the cache cannot serve *repo*, or ``""``.

    Args:
        target: the host, path and port the request went to, for the message.
        repo: the repository the route proxies onto.
        head: the response header block from :func:`response_head`.
        marker: the header the frontend carries ``$upstream_header_time`` in.
    """
    code, headers = parse_head(head)
    timing = headers.get(marker.lower(), "")
    if not nexus_answered(timing):
        return (
            f"{target} answered {code!r} with {marker} {timing!r}, so nginx got "
            f"no response from Nexus; the frontend did not reach repository {repo}"
        )
    if code == NEXUS_IO_FAILURE:
        return (
            f"{target} answered {code!r} from Nexus: Nexus could not reach "
            f"upstream for repository {repo}, or could not store what it fetched"
        )
    return ""


def check_nexus_is_up() -> None:
    code = status(NEXUS, f"http://127.0.0.1:{PORT}/service/rest/v1/status")
    if code != "200":
        failures.append(f"Nexus status endpoint answered {code!r}, want 200")


def check_every_declared_repository_exists() -> None:
    """Ask the registry which repositories Nexus holds."""
    code, body = run(
        NEXUS,
        [
            "curl",
            "-sS",
            "-k",
            "--max-time",
            "30",
            f"http://127.0.0.1:{PORT}/service/rest/v1/repositories",
        ],
    )
    if code != 0:
        failures.append("Nexus did not answer the repository registry")
        return

    held = {entry.get("name") for entry in json.loads(body)}
    failures.extend(
        f"repository {name} is declared but Nexus does not hold it; "
        "the bootstrap did not create it"
        for name in sorted(set(REPOS) - held)
    )


def check_frontend_serves_a_cert_per_tls_host() -> None:
    for entry in HOSTS:
        if not any(listener.get("tls") for listener in entry.get("listen", [])):
            continue
        host = entry["host"]
        for suffix in ("crt", "key"):
            code, _ = run(FRONTEND, ["test", "-s", f"{CERTS_DIR}/{host}.{suffix}"])
            if code != 0:
                failures.append(
                    f"{host} is served over TLS but {CERTS_DIR}/{host}.{suffix} "
                    "is missing or empty, so nginx cannot complete a handshake"
                )


def check_every_host_is_proxied() -> None:
    """Each cached hostname must reach its repository through the frontend."""
    for entry in HOSTS:
        host = entry["host"]
        for listener in entry.get("listen", []):
            scheme = "https" if listener.get("tls") else "http"
            port = listener.get("port")
            for route in entry.get("routes", []):
                url = f"{scheme}://127.0.0.1:{port}{route['path']}"
                verdict = proxied_verdict(
                    f"{host}{route['path']} on port {port}",
                    route["repo"],
                    response_head(FRONTEND, url, host),
                    MARKER,
                )
                if verdict:
                    failures.append(verdict)


def main() -> int:
    check_nexus_is_up()
    check_every_declared_repository_exists()
    check_frontend_serves_a_cert_per_tls_host()
    check_every_host_is_proxied()

    if failures:
        for line in failures:
            print(f"[FAIL] {line}", file=sys.stderr)
        return 1
    print(f"OK: {len(REPOS)} repositories and {len(HOSTS)} hosts served by the cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
