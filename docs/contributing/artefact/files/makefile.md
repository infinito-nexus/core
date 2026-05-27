# `Makefile` 🛠️

This page covers the rules that govern how the repository `Makefile` is written and structured.
For the full index of available `make` targets, see [make.md](../../tools/make.md).

## Target Design 📐

The `Makefile` is the human-facing command surface for the repo.
It MUST expose stable targets that people and CI are meant to run directly.

- You MUST keep public targets stable, named clearly, and documented.
- You MUST NOT add a target unless a human operator or CI should run it directly.
- You MUST keep helper-only logic, plumbing, and intermediate steps in `scripts/` or other implementation files.
- You SHOULD prefer targets that compose smaller scripts instead of embedding large shell fragments in the `Makefile`.
- You MUST keep the command surface small enough that contributors can discover the obvious path quickly.

For the broader architecture context, see [architecture.md](../../design/architecture.md).
