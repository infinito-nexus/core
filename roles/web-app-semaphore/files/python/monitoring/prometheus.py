from __future__ import annotations

import json

from monitoring.survey import RunError, path_host

FEDERATE_PATH = "/federate"
FEDERATE_MATCH = '{__name__=~".+"}'
FILE_SUFFIX = ".yml"
FILE_SEPARATOR = "__"


def scrape_file_name(workspace, host):
    return f"{workspace}{FILE_SEPARATOR}{path_host(host)}{FILE_SUFFIX}"


def scrape_config(workspace, host, entry, token):
    """Args:
    workspace: ``ws-<id>``.
    host: the inventory host.
    entry: its plan entry.
    token: its federation bearer token.

    Returns:
        The content of the host's scrape configuration file, which scrapes
        the instance's ``/federate`` with its token over a verified
        certificate and labels every series with ``workspace`` and
        ``instance``; the instance answers only the kinds its customer shares,
        whatever ``match[]`` asks.
    """
    return json.dumps(
        {
            "scrape_configs": [
                {
                    "job_name": f"instance-{workspace}-{path_host(host)}",
                    "scheme": "https",
                    "metrics_path": FEDERATE_PATH,
                    "honor_labels": False,
                    "follow_redirects": False,
                    "params": {"match[]": [FEDERATE_MATCH]},
                    "authorization": {"type": "Bearer", "credentials": token},
                    "tls_config": {"insecure_skip_verify": False},
                    "static_configs": [
                        {
                            "targets": [entry["federation"]],
                            "labels": {"workspace": workspace, "instance": host},
                        }
                    ],
                }
            ]
        },
        indent=2,
        sort_keys=True,
    )


def prometheus_state(planned, token):
    """Returns:
    ``workspace``, ``file``, ``instance`` and ``content``, the scrape
    configuration of MONITOR_HOST; None when it shares no Prometheus kind,
    which makes prometheus_instances.py delete that one file.
    """
    workspace, host, entry = planned["alias"], planned["host"], planned["entry"]
    content = None
    if entry and entry["prometheus"]:
        if not token:
            raise RunError(
                f"{host} shares a Prometheus kind but holds no federation token"
            )
        content = scrape_config(workspace, host, entry, token)
    return {
        "workspace": workspace,
        "file": scrape_file_name(workspace, host),
        "instance": host,
        "content": content,
    }
