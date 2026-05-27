def systemd_directive(value, key: str) -> str:
    """
    Render a single systemd directive line if value is non-empty.
    Example: {{ myval | systemd_directive('ExecStart') }}
    """
    if value is None:
        return ""
    sval = str(value).strip()
    if not sval:
        return ""
    return f"{key}={sval}"


class FilterModule:
    def filters(self):
        return {
            "systemd_directive": systemd_directive,
        }
