# Terminal Aliases 🐚

The [alias](https://github.com/kevinveenbirkenbach/alias) repository is the RECOMMENDED way to define CLI shortcuts so frequently used commands do not have to be retyped.
The effective repository is the `INFINITO_ALIAS_REPOSITORY` value in the generated `.env`.

## Usage 🚀

- Run `make alias` to print the terminal aliases together with the [agent aliases](../agents/alias.md).
- Run `make install-alias` to install the aliases into your shell config; afterwards open a new shell or `source ~/.bashrc`.

## Custom Repository 🛠️

Override `INFINITO_ALIAS_REPOSITORY` via `custom.env` as described in [customize.md](../../customize.md).
The repository MUST provide an `aliases` file at its root and a `make install` target.
Agent shortcuts MUST NOT collide with the terminal aliases of the effective repository; the external test suite enforces this against the generated `.env`.
