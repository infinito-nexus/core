def wazuh_agent_deps_problems(manifest_lines, pinned):
    """Compare the per-library manifests of a ``make deps`` tree with their pins.

    Args:
        manifest_lines: ``"<entry> <sha256>"`` lines, one per top-level entry of ``src/src/external``.
        pinned: mapping of entry name to its pinned SHA-256.

    Returns:
        Sorted problem strings, one per entry whose hash differs, that is pinned but missing,
        or that is present but not pinned; empty when every entry matches its pin.
    """
    actual = dict(line.split(" ", 1) for line in manifest_lines if line.strip())
    problems = []
    for name in sorted(set(actual) | set(pinned)):
        if name not in actual:
            problems.append(f"{name}: pinned but missing")
        elif name not in pinned:
            problems.append(f"{name}: not pinned, hash {actual[name]}")
        elif actual[name] != pinned[name]:
            problems.append(f"{name}: hash {actual[name]}, pin {pinned[name]}")
    return problems


class FilterModule:
    def filters(self):
        return {"wazuh_agent_deps_problems": wazuh_agent_deps_problems}
