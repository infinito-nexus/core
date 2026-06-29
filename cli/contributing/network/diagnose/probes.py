"""Per-host probes: DNS, TCP, TLS handshake, path MTU."""

from __future__ import annotations

import socket
import ssl
import time
from typing import TYPE_CHECKING

from cli.contributing.network.diagnose.config import PMTU_PROBE_SIZES
from cli.contributing.network.diagnose.format import cmd_capture, line, section

if TYPE_CHECKING:
    from collections.abc import Sequence


def dns_resolve(host: str, family: int) -> tuple[bool, str, str | None]:
    """Return (ok, info_string, first_address_or_None)."""
    start = time.monotonic()
    try:
        infos = socket.getaddrinfo(host, 443, family=family, type=socket.SOCK_STREAM)
        addrs = sorted({i[4][0] for i in infos})
        if not addrs:
            return False, "no addresses returned", None
        return True, f"{','.join(addrs)} ({time.monotonic() - start:.2f}s)", addrs[0]
    except (socket.gaierror, OSError) as e:
        return (
            False,
            f"{type(e).__name__} after {time.monotonic() - start:.2f}s: {e}",
            None,
        )


def tcp_connect(
    addr: str, family: int, port: int = 443, timeout: float = 5.0
) -> tuple[bool, str]:
    start = time.monotonic()
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((addr, port))
        peer = s.getpeername()
        s.close()
        return (
            True,
            f"connected to {peer[0]}:{peer[1]} ({time.monotonic() - start:.2f}s)",
        )
    except (socket.gaierror, OSError, TimeoutError) as e:
        return False, f"{type(e).__name__} after {time.monotonic() - start:.2f}s: {e}"


def tls_handshake(
    host: str, addr: str, family: int, port: int = 443, timeout: float = 8.0
) -> tuple[bool, str]:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    start = time.monotonic()
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((addr, port))
        with ctx.wrap_socket(s, server_hostname=host) as tls:
            cert = tls.getpeercert() or {}
            cn = _common_name(cert)
            proto = tls.version()
            dt = time.monotonic() - start
            return True, f"OK {proto} cn={cn or '?'} ({dt:.2f}s)"
    except (ssl.SSLError, OSError, TimeoutError) as e:
        return False, f"{type(e).__name__} after {time.monotonic() - start:.2f}s: {e}"


def _common_name(cert: dict) -> str:
    for rdn in cert.get("subject", ()):
        for k, v in rdn:
            if k == "commonName":
                return v
    return ""


def path_mtu_probe(host: str, family: int) -> tuple[int | str | None, int | str | None]:
    """Probe the largest ICMP-DF payload that survives without fragmentation.

    Returns:
      - ``(payload_bytes, total_bytes)`` on success
      - ``("SKIPPED", reason)`` when ping is unavailable or lacks CAP_NET_RAW
      - ``(None, None)`` when every probe size is dropped
    """
    binary = "ping" if family == socket.AF_INET else "ping6"
    df_flag = "-Mdo"
    rc_probe, out_probe = cmd_capture(
        [binary, "-c", "1", "-W", "1", df_flag, "-s", "56", host], timeout=3.0
    )
    if rc_probe == -1:
        return "SKIPPED", "ping binary not installed"
    if "Operation not permitted" in out_probe or "Lacking privilege" in out_probe:
        return "SKIPPED", "ping lacks CAP_NET_RAW"
    for size in PMTU_PROBE_SIZES:
        rc, _ = cmd_capture(
            [binary, "-c", "1", "-W", "2", df_flag, "-s", str(size), host],
            timeout=5.0,
        )
        if rc == 0:
            overhead = 28 if family == socket.AF_INET else 48
            return size, size + overhead
    return None, None


def per_host_check(hosts: Sequence[str], family: int, family_label: str) -> None:
    section(f"per-host DNS / TCP / TLS / PMTU ({family_label}, {len(hosts)} hosts)")
    for h in hosts:
        print(f"\n>>> {h} [{family_label}]")
        ok_dns, info_dns, addr = dns_resolve(h, family)
        line("DNS", f"[{'OK' if ok_dns else 'FAIL'}] {info_dns}")
        if not ok_dns or addr is None:
            line("TCP", "[SKIP] DNS failed")
            line("TLS", "[SKIP] DNS failed")
            line("PMTU", "[SKIP] DNS failed")
            continue
        ok_tcp, info_tcp = tcp_connect(addr, family)
        line("TCP", f"[{'OK' if ok_tcp else 'FAIL'}] {info_tcp}")
        if not ok_tcp:
            line("TLS", "[SKIP] TCP failed")
            line("PMTU", "[SKIP] TCP failed")
            continue
        ok_tls, info_tls = tls_handshake(h, addr, family)
        line("TLS", f"[{'OK' if ok_tls else 'FAIL'}] {info_tls}")
        payload, total = path_mtu_probe(addr, family)
        if payload == "SKIPPED":
            line("PMTU", f"[SKIP] {total}")
        elif payload is None:
            line("PMTU", "[FAIL] all probe sizes lost")
        else:
            line(
                "PMTU",
                f"[OK] payload={payload}B (total ~{total}B with IP+ICMP headers)",
            )
