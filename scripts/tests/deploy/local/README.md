# Local Deploy Test Scripts 🧪

This file describes the local helpers outside `deploy/`.
For executable local deploy flows, use [deploy/README.md](deploy/README.md).
For inventory reset helpers, use [reset/README.md](reset/README.md).
For cleanup helpers, use [purge/README.md](purge/README.md).
For container exec helpers, use [exec/README.md](exec/README.md).
For the canonical Make target index that invokes these helpers, see [make.md](../../../../docs/contributing/tools/make.md).

## Prerequisites

- Run commands from the repository root.
- Docker and Docker Compose are available locally.
- If you run scripts directly, load the defaults with `source scripts/meta/env/all.sh`.
