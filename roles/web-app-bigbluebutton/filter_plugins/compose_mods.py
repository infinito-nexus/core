import re

from utils.cache.yaml import dump_yaml_str, load_yaml_str


def compose_mods(
    yml_text,
    compose_repository_path,
    env_file,
    container_logging,
    extra_hosts=None,
    pinned=None,
):
    """Normalize the upstream-generated bigbluebutton compose file.

    Args:
        yml_text: compose YAML as produced by upstream generate-compose.
        compose_repository_path: absolute path of the packaging-repo clone;
            all repo-relative ``./`` paths are rewritten against it because
            the final file lives in the instance dir, not the clone.
        env_file: env file broadcast to every service via ``env_file``.
        container_logging: the rendered logging contract
            (``roles/sys-svc-container/templates/logging.yml.j2``) as a
            mapping with ``labels`` and ``logging``; its labels are merged
            into and its logging block replaces every service's own.
        extra_hosts: optional host mappings added to every service that is
            not on the host network.
        pinned: names of services whose image the role pins in
            compose.override.yml; their upstream ``build`` is dropped even
            where the upstream file names no image.

    Returns:
        Transformed compose YAML text. Structural deltas (named data
        volumes, healthchecks, per-service tweaks) live in
        compose.override.yml.j2, not here.
    """
    prefix = compose_repository_path.rstrip("/") + "/"
    yml_text = re.sub(r"\./", prefix, yml_text)
    yml_text = re.sub(
        r"(^\s*context:\s*)mod/(.*)",
        r"\1" + prefix + r"mod/\2",
        yml_text,
        flags=re.MULTILINE,
    )

    contract_labels = container_logging["labels"]
    contract_logging = container_logging["logging"]

    data = load_yaml_str(yml_text) or {}
    services = data.get("services", {}) or {}

    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue

        svc["env_file"] = [env_file]

        labels = svc.get("labels")
        if isinstance(labels, list):
            labels = {
                key: value
                for key, _, value in (str(entry).partition("=") for entry in labels)
            }
        elif not isinstance(labels, dict):
            labels = {}
        svc["labels"] = {**labels, **contract_labels}
        svc["logging"] = dict(contract_logging)

        if extra_hosts and svc.get("network_mode") != "host":
            hosts = svc.get("extra_hosts")
            if isinstance(hosts, dict):
                hosts = [f"{k}:{v}" for k, v in hosts.items()]
            elif not isinstance(hosts, list):
                hosts = []
            for entry in extra_hosts:
                if entry not in hosts:
                    hosts.append(entry)
            svc["extra_hosts"] = hosts

        if "build" in svc and (svc.get("image") or name in (pinned or [])):
            svc.pop("build")

    data["services"] = services
    return dump_yaml_str(data)


class FilterModule:
    def filters(self):
        return {
            "compose_mods": compose_mods,
        }
