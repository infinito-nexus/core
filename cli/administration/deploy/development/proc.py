from __future__ import annotations

import subprocess
import sys
import threading
from typing import TextIO


def _drain_stream(
    stream: TextIO,
    *,
    sink: TextIO,
) -> None:
    """
    Read a text stream line-by-line and write to sink.
    """
    try:
        for line in iter(stream.readline, ""):
            sink.write(line)
            sink.flush()
    finally:
        try:
            stream.close()
        except Exception as exc:
            sys.stderr.write(f"Warning: failed to close stream {stream!r}: {exc}\n")
            sys.stderr.flush()


def run_streaming(
    cmd: list[str],
    *,
    cwd,
    env: dict[str, str],
    text: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run a subprocess and stream stdout/stderr live to the terminal.
    """
    p = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        bufsize=1,  # line buffered (best effort)
    )

    # Type-narrowing asserts so the type checker sees the streams as
    # non-None below (PIPE was passed); these never fire at runtime.
    assert p.stdout is not None  # noqa: S101
    assert p.stderr is not None  # noqa: S101

    t_out = threading.Thread(
        target=_drain_stream,
        kwargs={"stream": p.stdout, "sink": sys.stdout},
    )
    t_err = threading.Thread(
        target=_drain_stream,
        kwargs={"stream": p.stderr, "sink": sys.stderr},
    )

    t_out.daemon = True
    t_err.daemon = True
    t_out.start()
    t_err.start()

    rc = p.wait()

    # Process is finished; drain threads should finish quickly too.
    t_out.join()
    t_err.join()

    return subprocess.CompletedProcess(cmd, rc)
