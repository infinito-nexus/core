#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

DOMAIN_FROM_FILENAME_RE = re.compile(r"^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\.conf$")

LISTEN_443_RE = re.compile(r"^\s*listen\s+[^;]*\b443\b", re.IGNORECASE)
LISTEN_80_RE = re.compile(r"^\s*listen\s+[^;]*\b80\b", re.IGNORECASE)
LISTEN_SSL_RE = re.compile(r"^\s*listen\s+[^;]*\bssl\b", re.IGNORECASE)


def extract_domains_from_filenames(config_path: str) -> list[str] | None:
    """
    Extract domain names from .conf filenames in the given directory.

    Example:
      baserow.<primary-domain>.conf -> baserow.<primary-domain>
    """
    try:
        out: list[str] = []
        for fn in os.listdir(config_path):
            if not fn.endswith(".conf"):
                continue
            if not DOMAIN_FROM_FILENAME_RE.match(fn):
                continue
            out.append(fn.removesuffix(".conf"))
    except FileNotFoundError:
        print(f"Directory {config_path} not found.", file=sys.stderr)
        return None
    return out


def collect_vhosts(servers_dir: str) -> dict[str, Path] | None:
    """Map every served vhost domain to its conf across ``http`` and ``https``.

    Args:
        servers_dir: the nginx ``servers`` directory holding ``http/`` and
            ``https/``.

    Returns:
        ``{domain: conf}``; a domain present in both keeps its ``https`` conf,
        since its ``http`` one is only the redirect to it. ``None`` when
        neither directory exists.
    """
    vhosts: dict[str, Path] = {}
    found = False
    for protocol in ("http", "https"):
        directory = Path(servers_dir) / protocol
        if not directory.is_dir():
            continue
        found = True
        for domain in extract_domains_from_filenames(str(directory)) or []:
            if protocol == "https" or domain not in vhosts:
                vhosts[domain] = directory / f"{domain}.conf"
    if not found:
        print(f"Directory {servers_dir} holds no http/ or https/.", file=sys.stderr)
        return None
    return vhosts


def split_proxied_domains(
    domains: list[str], proxy_suffix: str
) -> tuple[list[str], list[str]]:
    """Split into (direct, proxied): vhosts under ``proxy_suffix`` need the
    network's proxy to be probed."""
    if not proxy_suffix:
        return list(domains), []
    direct = [d for d in domains if not d.endswith(proxy_suffix)]
    proxied = [d for d in domains if d.endswith(proxy_suffix)]
    return direct, proxied


def is_skipped_domain(
    domain: str, skip_set: set[str], skip_labels: set[str], proxy_suffix: str
) -> bool:
    """Whether a domain should be excluded from the CSP probe.

    A domain is skipped if it is listed explicitly in ``--skip-domain``, or if
    it is the proxied sibling of a skipped vhost. Siblings of the same app
    share the leftmost subdomain label, so ``--skip-domain mirror.<primary>``
    also drops ``mirror.<node>``, which serves the same 4xx at ``/``.
    """
    if domain in skip_set:
        return True
    return (
        bool(proxy_suffix)
        and domain.endswith(proxy_suffix)
        and domain.split(".", 1)[0] in skip_labels
    )


def expand_accept_status(
    accept_status: list[str], domains: list[str], proxy_suffix: str
) -> list[str]:
    """ACCEPT_STATUS plus the same codes for every proxied sibling it covers.

    The checker matches accepted codes by hostname, and a vhost and its
    proxied twin share only the leftmost subdomain label, so a code declared
    for ``mirror.<primary>`` never reaches ``mirror.<node>`` on its own.

    Args:
        accept_status: ``<domain>=<code>[,<code>]`` entries as declared.
        domains: every vhost the probe covers.
        proxy_suffix: suffix of the network reached through the proxy.
    """
    _, proxied = split_proxied_domains(domains, proxy_suffix)
    expanded = list(accept_status)
    for entry in accept_status:
        host, _, codes = entry.partition("=")
        if not codes or (proxy_suffix and host.endswith(proxy_suffix)):
            continue
        label = host.split(".", 1)[0]
        expanded.extend(
            f"{sibling}={codes}"
            for sibling in proxied
            if sibling.split(".", 1)[0] == label
        )
    return expanded


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


def build_urls_from_nginx_confs(
    vhosts: dict[str, Path], domains: list[str]
) -> list[str]:
    """
    Build full URLs (http:// or https://) for each domain by inspecting its .conf file.

    Args:
        vhosts: ``collect_vhosts`` output.
        domains: the domains to build URLs for.
    """
    urls: list[str] = []

    for domain in domains:
        conf = vhosts[domain]
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
    timeout_ms: int = 0,
    accept_status: list[str] | None = None,
) -> list[str]:
    cmd = ["container", "run", "--rm"]

    if use_host_network:
        cmd.extend(["--network", "host"])

    # Exception: runs as root because with-ca-trust.sh installs the CA into the
    # container trust store, which an unprivileged user cannot write to.
    cmd.extend(["--user", "0:0"])

    cmd.append(image)

    if short_mode:
        cmd.append("--short")

    if proxy:
        cmd.extend(["--proxy", proxy])

    if timeout_ms:
        cmd.extend(["--timeout", str(timeout_ms)])

    if ignore_network_blocks_from:
        cmd.append("--ignore-network-blocks-from")
        cmd.extend(ignore_network_blocks_from)

    if accept_status:
        cmd.append("--accept-status")
        cmd.extend(accept_status)

    if ignore_network_blocks_from or accept_status:
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
    timeout_ms: int = 0,
    accept_status: list[str] | None = None,
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
        timeout_ms=timeout_ms,
        accept_status=accept_status,
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
        help="NGINX servers directory holding the http/ and https/ vhost confs",
    )
    parser.add_argument(
        "--proxy-suffix",
        required=True,
        help="Domain suffix of the network whose vhosts are probed through --tor-proxy",
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
        "--accept-status",
        nargs="*",
        default=[],
        help=(
            "Per-vhost status codes the probe must treat as healthy, as "
            "<domain>=<code>[,<code>]. Declared in the role's "
            "server.status_codes; everything below 300 passes without being "
            "listed."
        ),
    )
    parser.add_argument(
        "--onion-timeout",
        type=int,
        default=0,
        help=(
            "Navigation budget in milliseconds for the .onion batch, which "
            "reaches its vhosts over Tor and needs longer than the checker's "
            "own default. 0 leaves that default in place."
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

    vhosts = collect_vhosts(args.nginx_config_dir)
    if vhosts is None:
        sys.exit(1)

    domains = sorted(vhosts)
    if not domains:
        print("No domains found to check.")
        sys.exit(0)

    proxy_suffix = args.proxy_suffix
    skip_set = {d for d in (args.skip_domain or []) if d}
    if skip_set:
        skip_labels = {d.split(".", 1)[0] for d in skip_set}
        skipped_present = sorted(
            d
            for d in domains
            if is_skipped_domain(d, skip_set, skip_labels, proxy_suffix)
        )
        domains = [
            d
            for d in domains
            if not is_skipped_domain(d, skip_set, skip_labels, proxy_suffix)
        ]
        if skipped_present:
            print(
                f"Skipping {len(skipped_present)} domain(s) per "
                f"--skip-domain: {skipped_present}"
            )

    accept_status = expand_accept_status(
        list(args.accept_status or []), domains, proxy_suffix
    )

    clearnet_domains, onion_domains = split_proxied_domains(domains, proxy_suffix)
    if onion_domains and not args.tor_proxy:
        print(
            f"Skipping {len(onion_domains)} proxied domain(s), no --tor-proxy "
            f"given: {sorted(onion_domains)}"
        )
        onion_domains = []

    if not clearnet_domains and not onion_domains:
        print("No domains left to check after applying --skip-domain.")
        sys.exit(0)

    rc = 0
    for batch_domains, batch_proxy, batch_timeout in (
        (clearnet_domains, "", 0),
        (onion_domains, args.tor_proxy, args.onion_timeout),
    ):
        if not batch_domains:
            continue
        urls = build_urls_from_nginx_confs(vhosts, batch_domains)
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
            timeout_ms=batch_timeout,
            accept_status=accept_status,
        )
        rc = rc or batch_rc
    sys.exit(rc)


if __name__ == "__main__":
    main()
