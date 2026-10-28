import base64
import io
import re

from utils.roles.applications.mounts import content_hash

SECTIONS = ("configs", "secrets")
HASH_LENGTH = 8


def compose_hashed_entries(compose):
    """Return the configs and secrets whose name carries the content hash of their file.

    Args:
        compose: the parsed compose.yml.

    Returns:
        ``[{name, file}]`` for every top-level config or secret named
        ``<role>_<key>_<sha8>`` with a ``file`` source, the shape the
        ``compose_volumes`` lookup writes. Explicitly named entries, which do
        not end in their own key and a hash, are left out.
    """
    entries = []
    for section in SECTIONS:
        for key, spec in ((compose or {}).get(section) or {}).items():
            if (
                not isinstance(spec, dict)
                or not spec.get("file")
                or not spec.get("name")
            ):
                continue
            name = str(spec["name"])
            if re.search(rf"_{re.escape(str(key))}_[0-9a-f]{{{HASH_LENGTH}}}$", name):
                entries.append({"name": name, "file": str(spec["file"])})
    return entries


def compose_rehashed_name(name, content_b64):
    """Return a hashed config or secret name with the hash of its file's current content.

    Args:
        name: the ``<role>_<key>_<sha8>`` name from compose.yml.
        content_b64: the file content as ``slurp`` returns it.

    Returns:
        The name with its last eight characters replaced by the hash the
        ``compose_volumes`` lookup computes: sha256 of the file read as UTF-8
        text with universal newlines, as ``utils.cache.files.read_text`` does.
    """
    text = io.StringIO(
        base64.b64decode(content_b64).decode("utf-8"), newline=None
    ).read()
    return name[:-HASH_LENGTH] + content_hash(text, HASH_LENGTH)


class FilterModule:
    def filters(self):
        return {
            "compose_hashed_entries": compose_hashed_entries,
            "compose_rehashed_name": compose_rehashed_name,
        }
