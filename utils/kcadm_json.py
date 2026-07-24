from __future__ import annotations

import json
from typing import Any


def json_from_noisy_stdout(text: Any) -> Any:
    """
    Parse JSON from output that may contain leading non-JSON noise, including
    lines that start with '[' (e.g. JVM warnings like "[0.001s][warning]...").

    Deterministic strategy:
      - scan for all occurrences of '[' and '{' in the output
      - attempt json.loads() starting from each occurrence (in order)
      - return the first successfully parsed JSON value
      - raise ValueError if none work
    """
    if text is None:
        raise ValueError("No output (None)")

    s = str(text).lstrip()
    if not s:
        raise ValueError("Empty output")

    candidates = []
    for ch in ("[", "{"):
        start = 0
        while True:
            idx = s.find(ch, start)
            if idx == -1:
                break
            candidates.append(idx)
            start = idx + 1

    candidates = sorted(set(candidates))
    if not candidates:
        raise ValueError("No JSON start delimiter found")

    last_err: Exception | None = None
    for idx in candidates:
        chunk = s[idx:].strip()
        try:
            return json.loads(chunk)
        except ValueError as e:
            last_err = e

    raise ValueError(f"Failed to parse JSON from noisy stdout: {last_err}")
