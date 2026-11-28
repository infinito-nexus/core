import json
import os
import re
import sys
import tempfile
from pathlib import Path


def read_settings(path):
    text = (path.read_text() if path.exists() else "").strip() or "{}"
    text = re.sub(
        r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/',
        lambda match: match[1] if match[1] is not None else " ",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'("(?:\\.|[^"\\])*")|,(\s*[}\]])',
        lambda match: match[1] if match[1] is not None else match[2],
        text,
    )
    result = json.loads(text)
    if not isinstance(result, dict):
        raise TypeError(f"Expected a settings object in {path}")
    return result


def merge(settings, guard):
    merged = dict(settings)
    for key, value in guard.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = merge(current, value)
        else:
            merged[key] = value
    return merged


def apply(path, guard):
    """Merge ``guard`` into the editor settings file at ``path``.

    Args:
        path: The ``User/settings.json`` of the editor, created when missing;
            a symlink stays a symlink and its target receives the write.
        guard: Settings to enforce; nested mappings merge key by key.

    Returns:
        True when the file was written, False when it already held the guard.
    """
    path = path.resolve()
    settings = read_settings(path)
    merged = merge(settings, guard)
    if merged == settings:
        return False
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(merged, ensure_ascii=False, indent=4) + "\n")
        Path(temporary).chmod(mode)
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def main():
    changed = apply(Path(sys.argv[1]), json.load(sys.stdin))
    print("CHANGED" if changed else "UNCHANGED")


if __name__ == "__main__":
    main()
