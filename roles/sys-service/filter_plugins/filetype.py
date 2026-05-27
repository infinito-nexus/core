from pathlib import Path


def filetype(path, full=False):
    """
    Extract file type (extension) from a given path.

    :param path: Path or filename
    :param full: If True, return the full extension (e.g., 'sh.j2'),
                 else only the last extension (e.g., 'sh').
    :return: Extension string without leading dot, or empty string if none.
    """
    if not path or not isinstance(path, str):
        return ""

    basename = Path(path).name

    if full:
        # Full extension chain (e.g., "script.sh.j2" -> "sh.j2")
        parts = basename.split(".", 1)
        if len(parts) == 2:
            return parts[1]
        return ""
    # Last extension only (e.g., "script.sh.j2" -> "j2", "script.py" -> "py")
    suffix = Path(basename).suffix
    return suffix[1:] if suffix else ""


class FilterModule:
    """Custom Jinja2 filters for Ansible"""

    def filters(self):
        return {"filetype": filetype}
