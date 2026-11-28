from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from utils.networks.reachability import TOR, network


def stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def run_probe(
    script: str, vhosts: tuple[str, ...], curl: str, retries: int
) -> subprocess.CompletedProcess[str]:
    """Args:
        script: the text of test.sh to run.
        vhosts: the vhost names the scratch servers dir holds under http/.
        curl: the body of the curl stub; it finds its own directory in "$0".
        retries: RETRIES of the run.

    Returns:
        The finished probe of public Tor, run from a scratch directory whose
        onion_ports.py stub passes, so the domain probes alone decide it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "http").mkdir()
        for vhost in vhosts:
            (root / "http" / f"{vhost}.conf").write_text("", encoding="utf-8")
        (root / "test.sh").write_text(script, encoding="utf-8")
        stub(root / "onion_ports.py", "exit 0")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub(bin_dir / "curl", curl)
        return subprocess.run(
            ["bash", str(root / "test.sh")],
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "TOR_SOCKS": "tor:9050",
                "ONION_SUFFIX": network(TOR).suffix,
                "NGINX_SERVERS_DIR": str(root),
                "RETRIES": str(retries),
                "SLEEP_SECONDS": "0",
                "TOR_DNSMASQ_CONF": str(root / "tor-onion.conf"),
                "TOR_CONTAINER": "tor",
                "TOR_FLAVOR": "public",
            },
            capture_output=True,
            text=True,
            check=False,
        )
