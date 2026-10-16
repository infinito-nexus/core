#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile

JOURNALCTL = [
    "journalctl",
    "--since",
    "1 day ago",
    "--no-pager",
    "--all",
    "--output=json",
    "--output-fields=MESSAGE,CONTAINER_ID,SYSLOG_IDENTIFIER,_SYSTEMD_UNIT",
]


def message_text(value):
    """Return a journal MESSAGE as one line of text.

    Args:
        value: the MESSAGE field; journald encodes non-UTF-8 messages as a list of bytes and a repeated field as a list of its values.

    Returns:
        The message with line breaks collapsed to spaces.
    """
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        value = bytes(value).decode("utf-8", errors="replace")
    elif isinstance(value, list):
        value = "\n".join(message_text(item) for item in value)
    return " ".join(str(value).splitlines())


def host_errors(lines):
    """Yield `source: message` for every non-container entry that mentions an error.

    Args:
        lines: iterable of journalctl JSON lines, one entry per line, consumed lazily.

    Returns:
        Iterator of readable error lines.
    """
    for line in lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        if "CONTAINER_ID" in entry:
            continue
        message = message_text(entry.get("MESSAGE", ""))
        if "error" not in message.lower():
            continue
        source = (
            entry.get("_SYSTEMD_UNIT") or entry.get("SYSLOG_IDENTIFIER") or "unknown"
        )
        yield f"{source}: {message}"


def main():
    print("Checking journalctl for error messages outside container logs...")
    with tempfile.TemporaryFile(
        mode="w+", encoding="utf-8", errors="replace"
    ) as stderr:
        with subprocess.Popen(
            JOURNALCTL,
            stdout=subprocess.PIPE,
            stderr=stderr,
            encoding="utf-8",
            errors="replace",
        ) as journal:
            errors = list(host_errors(journal.stdout))
        if journal.returncode != 0:
            stderr.seek(0)
            print(
                f"journalctl failed with exit code {journal.returncode}: {stderr.read().strip()}"
            )
            return 2
    if errors:
        print("Some errors were found:")
        print("\n".join(errors))
        return 1
    print("No errors found in the journal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
