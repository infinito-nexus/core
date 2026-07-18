#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

DOMAIN_FROM_FILENAME_RE = re.compile(r"^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\.conf$")

# Very small "listen" heuristics:
# - treat as HTTPS if we see "listen ... 443" OR "listen ... ssl"
# - treat as HTTP  if we see "listen ... 80"
LISTEN_443_RE = re.compile(r"^\s*listen\s+[^;]*\b443\b", re.IGNORECASE)
LISTEN_80_RE = re.compile(r"^\s*listen\s+[^;]*\b80\b", re.IGNORECASE)
LISTEN_SSL_RE = re.compile(r"^\s*listen\s+[^;]*\bssl\b", re.IGNORECASE)


def extract_domains_from_filenames(config_path: str) -> list[str] | None:
    """
    Extract domain names from .conf filenames in the given directory.

    Example:
      baserow.infinito.example.conf -> baserow.infinito.example
    """
    try:
        out: list[str] = []
        for fn in os.listdir(config_path):
            if not fn.endswith(".conf"):
                continue
            if not DOMAIN_FROM_FILENAME_RE.match(fn):
                continue
            out.append(fn[:-5])  # strip ".conf"
    except FileNotFoundError:
        print(f"Directory {config_path} not found.", file=sys.stderr)
        return None
    return out


def split_onion_domains(domains: list[str]) -> tuple[list[str], list[str]]:
    """Split into (clearnet, onion): onion vhosts need a SOCKS proxy to probe."""
    clearnet = [d for d in domains if not d.endswith(".onion")]
    onion = [d for d in domains if d.endswith(".onion")]
    return clearnet, onion


def detect_scheme_from_conf(conf_path: Path) -> str | None:
    """
    Decide whether this conf listens on HTTP or HTTPS.

    Rule:
      - If HTTPS is present -> return "https"
      - Else if HTTP present -> return "http"
      - Else -> None (unknown)

    Note:
      This is intentionally simple and "best effort".
    """
    try:
        text = conf_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None
    except Exception as exc:
        print(f"Failed to read {conf_path}: {exc}", file=sys.stderr)
        return None

    has_443 = False
    has_80 = False
    has_ssl = False

    for line in text:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if LISTEN_443_RE.search(line):
            has_443 = True
        if LISTEN_SSL_RE.search(line):
            has_ssl = True
        if LISTEN_80_RE.search(line):
            has_80 = True

    if has_443 or has_ssl:
        return "https"
    if has_80:
        return "http"
    return None


def build_urls_from_nginx_confs(config_path: str, domains: list[str]) -> list[str]:
    """
    Build full URLs (http:// or https://) for each domain by inspecting its .conf file.
    """
    base = Path(config_path)
    urls: list[str] = []

    for domain in domains:
        conf = base / f"{domain}.conf"
        scheme = detect_scheme_from_conf(conf)

        if scheme is None:
            print(
                f"Warning: Could not detect scheme from {conf}. Falling back to http://{domain}/",
                file=sys.stderr,
            )
            scheme = "http"

        urls.append(f"{scheme}://{domain}/")

    return urls


def build_docker_cmd(
    image: str,
    urls: list[str],
    short_mode: bool,
    ignore_network_blocks_from: list[str],
    use_host_network: bool = True,
    proxy: str = "",
) -> list[str]:
    cmd = ["container", "run", "--rm"]

    if use_host_network:
        cmd.extend(["--network", "host"])

    # IMPORTANT: allow with-ca-trust.sh to install CA into container trust store
    cmd.extend(["--user", "0:0"])

    cmd.append(image)

    if short_mode:
        cmd.append("--short")

    if proxy:
        cmd.extend(["--proxy", proxy])

    if ignore_network_blocks_from:
        cmd.append("--ignore-network-blocks-from")
        cmd.extend(ignore_network_blocks_from)
        cmd.append("--")

    cmd.extend(urls)
    return cmd


def run_checker(
    image: str,
    urls: list[str],
    short_mode: bool,
    ignore_network_blocks_from: list[str],
    always_pull: bool,
    use_host_network: bool = True,
    proxy: str = "",
) -> int:
    """
    Runs the CSP checker container and returns its exit code.
    Always uses run.
    """
    if always_pull:
        subprocess.run(["container", "pull", image], check=False)

    cmd = build_docker_cmd(
        image=image,
        urls=urls,
        short_mode=short_mode,
        ignore_network_blocks_from=ignore_network_blocks_from,
        use_host_network=use_host_network,
        proxy=proxy,
    )

    try:
        result = subprocess.run(cmd, check=False)
        return int(result.returncode)
    except FileNotFoundError:
        print("run not found. Please install it.", file=sys.stderr)
        return 127
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract NGINX domains and build URL(s) (http/https) from listen directives, then run CSP checker (Docker)."
    )
    parser.add_argument(
        "--nginx-config-dir",
        required=True,
        help="Directory containing NGINX .conf files",
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Docker image to run (e.g. ghcr.io/kevinveenbirkenbach/csp-checker:stable)",
    )
    parser.add_argument(
        "--always-pull",
        action="store_true",
        help="Pull the container image before running (best-effort).",
    )
    parser.add_argument(
        "--short",
        action="store_true",
        help="Enable short mode (one example per policy/type).",
    )
    parser.add_argument(
        "--ignore-network-blocks-from",
        nargs="*",
        default=[],
        help="Optional: domains whose network block failures should be ignored",
    )
    parser.add_argument(
        "--no-host-network",
        action="store_true",
        help="Disable --network host for container run (default is to use host network).",
    )
    parser.add_argument(
        "--skip-domain",
        nargs="*",
        default=[],
        help=(
            "Domains to exclude from the CSP probe. Used for roles whose "
            "server.status_codes.default permits a 4xx/5xx response at `/` "
            "(e.g. federation-only apps), which the csp-checker would "
            "otherwise treat as unreachable."
        ),
    )
    parser.add_argument(
        "--tor-proxy",
        default="",
        help=(
            "SOCKS proxy for probing .onion vhosts (e.g. "
            "socks5://127.0.0.1:9050). Without it, .onion domains are "
            "skipped — the checker cannot resolve them over plain DNS."
        ),
    )

    args = parser.parse_args()

    domains = extract_domains_from_filenames(args.nginx_config_dir)
    if domains is None:
        sys.exit(1)

    if not domains:
        print("No domains found to check.")
        sys.exit(0)

    skip_set = {d for d in (args.skip_domain or []) if d}
    if skip_set:
        skipped_present = sorted(skip_set & set(domains))
        domains = [d for d in domains if d not in skip_set]
        if skipped_present:
            print(
                f"Skipping {len(skipped_present)} domain(s) per "
                f"--skip-domain: {skipped_present}"
            )

    clearnet_domains, onion_domains = split_onion_domains(domains)
    if onion_domains and not args.tor_proxy:
        print(
            f"Skipping {len(onion_domains)} .onion domain(s) — no --tor-proxy "
            f"given: {sorted(onion_domains)}"
        )
        onion_domains = []

    if not clearnet_domains and not onion_domains:
        print("No domains left to check after applying --skip-domain.")
        sys.exit(0)

    rc = 0
    for batch_domains, batch_proxy in (
        (clearnet_domains, ""),
        (onion_domains, args.tor_proxy),
    ):
        if not batch_domains:
            continue
        urls = build_urls_from_nginx_confs(args.nginx_config_dir, batch_domains)
        if not urls:
            print(f"No URLs built to check for: {sorted(batch_domains)}")
            continue
        batch_rc = run_checker(
            image=args.image,
            urls=urls,
            short_mode=bool(args.short),
            ignore_network_blocks_from=list(args.ignore_network_blocks_from or []),
            always_pull=bool(args.always_pull),
            use_host_network=not bool(args.no_host_network),
            proxy=batch_proxy,
        )
        rc = rc or batch_rc
    sys.exit(rc)


if __name__ == "__main__":
    main()
