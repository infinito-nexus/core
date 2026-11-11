import re
import tomllib

from ansible.errors import AnsibleFilterError

_HEADER = re.compile(r"^\s*\[(\[?)([^\[\]]+)\]\]?\s*(?:#.*)?$")
_KEY = re.compile(r"^\s*([^=#\[\s][^=]*?)\s*=")


def _table_name(raw):
    return re.sub(r"\s*\.\s*", ".", raw.strip())


def _sections(lines):
    sections = [[None, None, []]]
    for line in lines:
        header = _HEADER.match(line)
        if header:
            sections.append([header.group(1) + _table_name(header.group(2)), line, []])
        else:
            sections[-1][2].append(line)
    return sections


def _key_of(line):
    match = _KEY.match(line)
    return match.group(1) if match else None


def _owned(managed):
    return [
        (name, [(_key_of(line), line) for line in body if _key_of(line)])
        for name, _, body in _sections(managed.splitlines())
    ]


def _leaves(data, prefix=()):
    for key, value in data.items():
        if isinstance(value, dict):
            yield from _leaves(value, (*prefix, key))
        else:
            yield (*prefix, key), value


def _without(data, paths):
    pruned = {}
    for key, value in data.items():
        if isinstance(value, dict):
            inner = _without(value, {path[1:] for path in paths if path[0] == key})
            if inner or value == {}:
                pruned[key] = inner
        elif (key,) not in paths:
            pruned[key] = value
    return pruned


def _parse(text, what):
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise AnsibleFilterError(f"{what} is not valid TOML: {exc}") from exc


def codex_config_merge(current, managed):
    """Set the keys the role owns in a Codex config.toml and keep every other line.

    Args:
        current: the config.toml text found on the host, empty when absent.
        managed: the rendered TOML holding only the keys the role owns.

    Returns:
        ``current`` with each owned key replaced in place, or added to its
        table when missing, and every foreign key, table and comment untouched.

    Raises:
        AnsibleFilterError: when either input is not valid TOML, or when the
        merged text would change a foreign value or miss an owned one, for
        example because the host defines an owned table as an inline table.
    """
    before = _parse(current, "the existing Codex config")
    wanted = _parse(managed, "the managed Codex profile")
    sections = _sections(current.splitlines())

    for name, entries in _owned(managed):
        section = next((s for s in sections if s[0] == name), None)
        if section is None:
            tail = sections[-1][2]
            if tail and tail[-1].strip():
                tail.append("")
            section = [name, f"[{name}]", []]
            sections.append(section)
        body = section[2]
        for key, line in entries:
            index = next((i for i, old in enumerate(body) if _key_of(old) == key), None)
            if index is not None:
                body[index] = line
                continue
            filled = [i for i, old in enumerate(body) if old.strip()]
            body.insert(filled[-1] + 1 if filled else 0, line)

    lines = []
    for _, header, body in sections:
        if header is not None:
            lines.append(header)
        lines.extend(body)
    merged = "\n".join(lines).rstrip("\n") + "\n"

    after = _parse(merged, "the merged Codex config")
    owned = {path for path, _ in _leaves(wanted)}
    for path, value in _leaves(wanted):
        node = after
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        if node != value:
            raise AnsibleFilterError(
                f"the merged Codex config does not carry {'.'.join(path)}"
            )
    if _without(before, owned) != _without(after, owned):
        raise AnsibleFilterError(
            "merging the gateway profile would change keys the role does not own"
        )
    return merged


class FilterModule:
    def filters(self):
        return {"codex_config_merge": codex_config_merge}
