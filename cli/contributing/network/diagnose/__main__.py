"""Network diagnostics for the infinito container (DNS, TCP, TLS, MTU, routing).

Intended to run early in MODE_DEBUG playbooks so handshake / DNS / MITM-style
failures show up loudly before any role-level pull/build hits them.
"""

from __future__ import annotations

from cli.contributing.network.diagnose.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
