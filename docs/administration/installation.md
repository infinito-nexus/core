# Installation Guide 🚀

Use this guide to install the `infinito` CLI with the method that fits your workflow.

## Run with Docker 🐳

Build the image and run the CLI. For more options, see [Docker and Runtime Commands](../contributing/tools/docker.md).

```bash
docker build -t infinito:latest .
docker run --rm -it infinito:latest infinito --help
```

## Develop from Source 💻

Clone the repository and install the project from the repository root:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make install
make environment-bootstrap
```

This prepares the repository for local development.

`make environment-bootstrap` also installs the repository's local `pre-commit` hooks for this checkout.

All available `make` commands are documented in the [Makefile Commands](../contributing/tools/make.md) reference.
For a worked example of how these commands interact (including build, bootstrap, test, deploy, and teardown), see the [environment test suite](../../scripts/tests/environment/README.md).
For further information on setting up a local development environment, see [CONTRIBUTING.md](../../CONTRIBUTING.md).

For inventory creation and deployment, continue with the [Deploy Guide](deploy.md).
