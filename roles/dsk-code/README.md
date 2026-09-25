# Code

## Description

[Visual Studio Code](https://github.com/microsoft/vscode) in a selectable flavor: the distribution's Code - OSS build, VSCodium, or Microsoft's own binary.

## Overview

`services.code.flavor` picks one of `code-oss`, `vscodium` or `vscode`. The three builds conflict at package level, so the role removes the other two before installing the chosen one.

The role also carries the editor extensions of the agents the same host deploys: when `dsk-gnt-claude` is in the host's groups, the Claude Code extension is installed into the chosen flavor. Code - OSS and VSCodium resolve extensions through Open VSX, which carries that extension as well.

`dsk-gnt-cursor` and `dsk-gnt-pi` carry no entry in that map. Cursor is a full editor rather than an extension, and neither vendor publishes an extension on Open VSX, so there is nothing to install into Code for them. Both agents are used from their own binary.

## Features

- **Flavor selectable:** one setting switches between Code - OSS, VSCodium and the Microsoft build.
- **Conflict-free switch:** the other flavors are removed first, because they claim the same binary.
- **Agent-aware:** an agent role on the same host brings its editor extension along.
- **Refused early:** an unknown flavor aborts the deploy with the list of carried flavors.
