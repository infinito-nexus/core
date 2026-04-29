import re

from utils.cache.yaml import dump_yaml_str, load_yaml_str


def compose_mods(yml_text, docker_repository_path, env_file):
    # Named volume rewrites
    yml_text = re.sub(
        r"\./data/postgres:/var/lib/postgresql/data",
        "database:/var/lib/postgresql/data",
        yml_text,
    )
    yml_text = re.sub(
        r"\./data/bigbluebutton:/var/bigbluebutton",
        "bigbluebutton:/var/bigbluebutton",
        yml_text,
    )
    yml_text = re.sub(
        r"\./data/freeswitch-meetings:/var/freeswitch/meetings",
        "freeswitch:/var/freeswitch/meetings",
        yml_text,
    )
    yml_text = re.sub(
        r"\./data/greenlight:/usr/src/app/storage",
        "greenlight:/usr/src/app/storage",
        yml_text,
    )
    yml_text = re.sub(
        r"\./data/mediasoup:/var/mediasoup", "mediasoup:/var/mediasoup", yml_text
    )

    # Make other ./ paths absolute to the given repository
    yml_text = re.sub(r"\./", docker_repository_path.rstrip("/") + "/", yml_text)

    # Keep the old context helpers (harmless if YAML step below fixes everything)
    yml_text = re.sub(
        r"(^\s*context:\s*)mod/(.*)",
        r"\1" + docker_repository_path.rstrip("/") + r"/mod/\2",
        yml_text,
        flags=re.MULTILINE,
    )

    def _prefix_mod(path: str) -> str:
        """Prefix 'mod/...' (or './mod/...') with docker_repository_path, avoiding //."""
        p = str(path).strip().strip("'\"")
        p = p.lstrip("./")
        if p.startswith("mod/"):
            return docker_repository_path.rstrip("/") + "/" + p
        return path

    try:
        data = load_yaml_str(yml_text) or {}
        services = data.get("services", {}) or {}

        for name, svc in services.items():
            if not isinstance(svc, dict):
                continue

            # ensure env_file
            svc["env_file"] = [env_file]

            # handle build when it is a string: e.g., build: "mod/periodic"
            if "build" in svc:
                b = svc["build"]
                if isinstance(b, str):
                    svc["build"] = _prefix_mod(b)
                elif isinstance(b, dict):
                    ctx = b.get("context")
                    if isinstance(ctx, str):
                        b["context"] = _prefix_mod(ctx)

            # extras
            if name == "redis":
                vols = svc.get("volumes")
                if not vols or not isinstance(vols, list):
                    svc["volumes"] = ["redis:/data"]
                elif "redis:/data" not in vols:
                    svc["volumes"].append("redis:/data")

            if name == "coturn":
                vols = svc.get("volumes")
                if not vols or not isinstance(vols, list):
                    svc["volumes"] = ["coturn:/var/lib/coturn"]
                elif "coturn:/var/lib/coturn" not in vols:
                    svc["volumes"].append("coturn:/var/lib/coturn")

            if name == "bbb-graphql-server":
                svc["healthcheck"] = {
                    "test": ["CMD", "curl", "-f", "http://localhost:8085/healthz"],
                    "interval": "30s",
                    "timeout": "10s",
                    "retries": 5,
                    "start_period": "10s",
                }

        data["services"] = services

        # Only add volumes block if not present
        data.setdefault(
            "volumes",
            {
                "database": None,
                "greenlight": None,
                "redis": None,
                "coturn": None,
                "freeswitch": None,
                "bigbluebutton": None,
                "mediasoup": None,
            },
        )

        yml_text = dump_yaml_str(data)
    except Exception:
        # leave the original yml_text as-is if parsing fails
        pass

    return yml_text


class FilterModule(object):
    def filters(self):
        return {
            "compose_mods": compose_mods,
        }
