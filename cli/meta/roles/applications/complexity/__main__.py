#!/usr/bin/env python3
"""Score every application role by the size of its transitive shared-service dependency closure."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
