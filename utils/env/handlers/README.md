# utils/env/handlers 🧩

Per-variable mapping logic for the `.env` generator.
For the package's overall role see [README.md](../README.md).
For general README conventions see [documentation.md](../../../docs/contributing/documentation.md).

## Purpose 🎯

Each module in this directory owns exactly one variable, or one tightly-coupled group resolved by a single helper call.
The orchestrator in [builder.py](../builder.py) iterates the registry in [__init__.py](__init__.py) and calls each handler's `apply(eb, ctx)` in order.

## File Naming 🏷️

- A handler module name MUST match the lowercase of the variable it owns:
  - `INFINITO_CONTAINER` -> `infinito/container.py`
  - `INFINITO_GHCR_MIRROR_PREFIX` -> `infinito/ghcr_mirror_prefix.py`
- The `infinito_` prefix in the filename MUST be present iff the owned key carries the `INFINITO_` prefix.
- Aggregate handlers (one helper call resolves several keys at once) MUST take the singular topic name without a key suffix.
  Example: `infinito/inventory.py` resolves `INFINITO_INVENTORY_DIR`, `INFINITO_INVENTORY_FILE`, and `INFINITO_INVENTORY_HOST_VARS_FILE` from one `scripts/inventory/resolve.sh` invocation.
- The trivial static passthroughs live in two collector files: `passthrough.py` (always emitted) and `gha_passthrough.py` (emitted only when `ctx.on_gha` is true).

## Module Shape 📐

Every handler module MUST expose the same surface so the registry can call it uniformly:

```python
"""<one-line docstring: what variable, what it derives from>."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_..."
COMMENT = "<single-line per-key comment, mirrors default.env style>"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    ...
```

- `KEY` MUST be the owned variable's name.
- `COMMENT` MUST be a single line, no em dashes, that ends up above the key in the generated `.env`.
- `apply` MUST take `(eb, ctx)` and return `None`.
- A handler that targets a conditional branch (GHA-only, NIX-only, ...) MUST self-check the relevant `ctx` flag and return early.
  The registry calls every handler unconditionally.

## Import Rules 🔗

- A handler MUST NOT import another handler.
  Cross-handler data flows through `eb.get(...)` / `eb.set(...)` only.
- A handler MAY import from [parser.py](../parser.py), [runtime.py](../runtime.py), and stdlib.
- A handler MUST NOT import from [writer.py](../writer.py) or [builder.py](../builder.py) at runtime.
  The `EnvBuilder` and `BuildContext` types MAY be referenced under `TYPE_CHECKING` for annotations only.

## Registry 📋

- [__init__.py](__init__.py) MUST list every handler module in `ORDERED_HANDLERS`.
- The order in `ORDERED_HANDLERS` MUST respect data dependencies.
  Example: `infinito_container` runs after `passthrough` so it can read the resolved `INFINITO_DISTRO`.
- Adding a handler MUST also bump the relevant baseline test in [test_dotenv_generator.py](../../../tests/integration/meta/env/test_dotenv_generator.py) when the new key is a static-default in [default.env](../../../default.env), so the drift test stays honest.
