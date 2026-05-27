# Derive a temporary cgroup memory ceiling for the one-off
# `npm run plugin:install` exec.
#
# Usage (Jinja):
#   {{ PEERTUBE_MEM_LIMIT
#        | install_mem_limit(PEERTUBE_OIDC_PLUGIN_INSTALL_MAX_OLD_SPACE_MB) }}
#
# Formula:
#   bytes(mem_limit) + install_heap_mb * overhead * 10^6
#
# Why `overhead` (default 4):
#   `--max-old-space-size=<MB>` caps only V8 old-generation heap. Actual RSS
#   during `npm install` is higher: V8 young-gen + code space, native malloc
#   (node-gyp C++ builds, native bindings), and spawned postinstall workers
#   with their own RSS. Empirically ~4× the heap cap for peertube plugin
#   installs — the overhead is the headroom above the main peertube process
#   (which keeps running in the same cgroup via `container exec`).
#
# Output: integer bytes. `container update --memory` / `docker update --memory`
# accepts a raw byte count.

from ansible.errors import AnsibleFilterError

try:
    from plugins.filter.node_autosize import _to_bytes
except Exception as e:
    raise AnsibleFilterError(
        f"Failed to import _to_bytes from plugins.filter.node_autosize: {e}"
    ) from e


def install_mem_limit(mem_limit, install_heap_mb, overhead: int = 4) -> int:
    """
    Return install-window cgroup memory ceiling in bytes.

    Args:
        mem_limit:        compose mem_limit of the long-running service
                          (e.g. "8g", "512m", int bytes).
        install_heap_mb:  V8 old-space cap used for the install exec, in MB
                          (decimal, matches Node's --max-old-space-size unit).
        overhead:         multiplier applied to install_heap_mb to cover
                          native RSS + spawned workers (default 4).
    """
    base_bytes = _to_bytes(mem_limit)
    if base_bytes is None:
        raise AnsibleFilterError(
            f"install_mem_limit: mem_limit is empty/None: {mem_limit!r}"
        )

    try:
        heap_mb = int(install_heap_mb)
    except Exception:
        raise AnsibleFilterError(
            f"install_mem_limit: install_heap_mb must be int-like, got: {install_heap_mb!r}"
        ) from None

    try:
        ov = int(overhead)
    except Exception:
        raise AnsibleFilterError(
            f"install_mem_limit: overhead must be int-like, got: {overhead!r}"
        ) from None

    if heap_mb <= 0:
        raise AnsibleFilterError(
            f"install_mem_limit: install_heap_mb must be > 0, got: {heap_mb}"
        )
    if ov <= 0:
        raise AnsibleFilterError(f"install_mem_limit: overhead must be > 0, got: {ov}")

    return base_bytes + heap_mb * ov * 10**6


class FilterModule:
    def filters(self):
        return {"install_mem_limit": install_mem_limit}
