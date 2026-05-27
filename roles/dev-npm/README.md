# npm

## Description

This Ansible role installs npm and optionally runs `npm ci` within a given project directory. It is intended to streamline dependency installation for Node.js applications.

## Overview

Designed for use in Node-based projects, this role installs npm and can execute a clean install (`npm ci`) to ensure consistent dependency trees.

## Features

- **npm Installation:** Ensures the `npm` package manager is installed.
- **Optional Project Setup:** Runs `npm ci` in a specified folder to install exact versions from `package-lock.json`.
- **Idempotent:** Skips `npm ci` if no folder is configured.

## Configuration

Set `npm_project_folder` to a directory containing `package.json` and `package-lock.json`:

```yaml
vars:
  npm_project_folder: /opt/scripts/my-node-project/
```

## License

Infinito.Nexus Community License (Non-Commercial)
[https://s.infinito.nexus/license](https://s.infinito.nexus/license)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
