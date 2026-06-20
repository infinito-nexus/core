# Agent iteration loops

This directory contains the iteration loops agents follow while driving a role end to end: the role-level baseline, the spec-only inner loop, and the recurring workflow cycle between deploys.
Its scope is the mechanics of those loops. It does not describe what individual artefacts must contain; those rules live under the relevant contributing SPOTs.

Host-tooling gotcha: on a recent Docker engine, `make act-*` (including the swarm targets) can fail at job setup before any deploy starts; see [Workflow Loop > Newer Docker breaks the stock act runner image](workflow.md#newer-docker-breaks-the-stock-act-runner-image).
