"""Single point of truth for diagnose constants."""

from __future__ import annotations

DEFAULT_HOSTS: tuple[str, ...] = (
    "github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "ghcr.io",
    "registry-1.docker.io",
    "auth.docker.io",
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
)

TOOLS: tuple[str, ...] = ("ping", "ip")

INSTALL_CMDS: dict[str, list[str]] = {
    "debian": [
        "apt-get",
        "install",
        "-y",
        "--no-install-recommends",
        "-o",
        "DPkg::Lock::Timeout=120",
        "iputils-ping",
        "iproute2",
    ],
    "ubuntu": [
        "apt-get",
        "install",
        "-y",
        "--no-install-recommends",
        "-o",
        "DPkg::Lock::Timeout=120",
        "iputils-ping",
        "iproute2",
    ],
    "arch": ["pacman", "-S", "--noconfirm", "--needed", "iputils", "iproute2"],
    "fedora": ["dnf", "install", "-y", "iputils", "iproute"],
    "centos": ["dnf", "install", "-y", "iputils", "iproute"],
    "rhel": ["dnf", "install", "-y", "iputils", "iproute"],
}

PROXY_ENV_KEYS: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "CA_TRUST_CERT_HOST",
    "CA_TRUST_NAME",
)

CA_BUNDLE_CANDIDATES: tuple[str, ...] = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
)

PMTU_PROBE_SIZES: tuple[int, ...] = (1472, 1452, 1400, 1300, 1200, 1024, 576, 256)

EXTRA_HOSTS_ENV = "INFINITO_NET_DEBUG_HOSTS"  # nocheck: ad-hoc probe override; not part of the env registry
