#!/usr/bin/python
from __future__ import annotations

import subprocess

from ansible.module_utils.basic import AnsibleModule


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip())
    return (p.stdout or "").strip()


def main():
    module = AnsibleModule(
        argument_spec={
            "network": {"type": "str", "default": "bridge"},
        },
        supports_check_mode=True,
    )

    network = module.params["network"]

    try:
        gw = run(
            [
                "docker",
                "network",
                "inspect",
                network,
                "--format",
                "{{ (index .IPAM.Config 0).Gateway }}",
            ]
        )
        module.exit_json(changed=False, gateway=gw)
    except Exception as e:
        module.fail_json(msg=str(e))


if __name__ == "__main__":
    main()
