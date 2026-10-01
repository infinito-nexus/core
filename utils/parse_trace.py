"""Print the files and the URLs a Playwright trace archive holds.

Usage:
  python -m utils.parse_trace <trace.zip>
"""

import re
import sys
import zipfile

URL = re.compile(r'https?://[^\s"\\]+')
LIMIT = 50
TRACE_SUFFIXES = (".trace", ".network")


def urls(archive: zipfile.ZipFile, name: str) -> list[str]:
    """Return up to ``LIMIT`` distinct URLs found in one member of ``archive``.

    Args:
        archive: the opened trace archive.
        name: the member to scan.
    """
    if name not in archive.namelist():
        return []
    text = archive.read(name).decode(errors="replace")
    seen: set[str] = set()
    for match in URL.finditer(text):
        seen.add(match.group(0).rstrip('",:;)'))
        if len(seen) >= LIMIT:
            break
    return sorted(seen)


def main(argv: list[str] | None = None) -> int:
    """Print the archive's trace members and the URLs they mention.

    Args:
        argv: command line arguments; ``sys.argv[1:]`` when omitted.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    with zipfile.ZipFile(args[0]) as archive:
        print("==== files in trace ====")
        for name in archive.namelist():
            if name.endswith(TRACE_SUFFIXES):
                print(name, archive.getinfo(name).file_size)

        for member in ("0-trace.network", "0-trace.trace"):
            print()
            print(f"==== url-like strings from {member} (first {LIMIT}) ====")
            for url in urls(archive, member):
                print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
