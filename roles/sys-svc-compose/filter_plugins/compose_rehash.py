import re

from plugins.lookup.compose_volumes import _config_secret_name

SECTIONS = ("configs", "secrets")
HASH_LENGTH = 8


def compose_hashed_entries(compose):
    """Return the configs and secrets whose name carries the content hash of their file.

    Args:
        compose: the parsed compose.yml.

    Returns:
        ``[{name, entity, key, file}]`` for every top-level config or secret
        named ``<entity>_<key>_<sha8>`` with a ``file`` source, the shape the
        ``compose_volumes`` lookup writes. Explicitly named entries, which do
        not end in their own key and a hash, are left out.
    """
    entries = []
    for section in SECTIONS:
        for key, spec in (compose.get(section) or {}).items():
            if (
                not isinstance(spec, dict)
                or not spec.get("file")
                or not spec.get("name")
            ):
                continue
            name = str(spec["name"])
            match = re.fullmatch(
                rf"(?P<entity>.+)_{re.escape(str(key))}_[0-9a-f]{{{HASH_LENGTH}}}", name
            )
            if match:
                entries.append(
                    {
                        "name": name,
                        "entity": match["entity"],
                        "key": str(key),
                        "file": str(spec["file"]),
                    }
                )
    return entries


def compose_rehashed_name(entry):
    """Return the name the ``compose_volumes`` lookup gives an entry's file as it is now.

    Args:
        entry: one item of ``compose_hashed_entries``.

    Returns:
        ``<entity>_<key>_<sha8>`` from the lookup's own naming function, read
        on the controller like the render, so an unchanged file keeps exactly
        the name the next render writes.
    """
    return _config_secret_name(entry["entity"], entry["key"], entry["file"])


class FilterModule:
    def filters(self):
        return {
            "compose_hashed_entries": compose_hashed_entries,
            "compose_rehashed_name": compose_rehashed_name,
        }
