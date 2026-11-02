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
- **Claude profiles:** `addons.claude-code.config.profiles` creates named native editor profiles and installs Claude into each. Each entry specifies `name`, `mode` (`gateway` or `subscription`), `model`, and `context_tokens` (an integer or `null`). Gateway profiles require a model; subscription profiles use the saved Claude login. Set `config.user_data_dir` to the editor's absolute data directory and `config.gateway_url` to the gateway root URL. The key comes from the Claude role's existing credentials.
- **Refused early:** an unknown flavor aborts the deploy with the list of carried flavors.

Close all editor windows before deploying profiles: the role refuses to update an open profile registry. Legacy profiles preserve unrelated values. Settings are written as JSON with owner-only permissions.

Enabled agent extensions, including Codex, are also installed into every managed
Claude profile after registration.

## One managed Claude profile

Set `addons.claude-code.config.unified` instead of the legacy `profiles` list.
The mapping requires `name`, `initial_mode` (`gateway` or `abo`), `subscription_model`, `model`,
`background_model`, `context_tokens`, `max_output_tokens`, `gateway_models`,
`retire_profiles`, and `settings`. Each `gateway_models` row supplies `model`,
`label`, and `description`. The ordered list replaces the built-in picker rows
in gateway mode; subscription mode restores the built-in picker.
The `model` and `background_model` can reference the Claude role's service
settings, so their inventory declaration stays in one place.

The unified mode writes `~/.claude/settings.json`, the editor's default settings
and the named Claude profile from the inventory. `services.code.settings` owns
the general editor settings, including `window.autoDetectColorScheme` and the
preferred light/dark themes. `unified.settings` owns other Claude settings;
`env`, `model`, `modelPicker`, and `apiKeyHelper` are reserved for the connection switch.
Manual settings in these managed files are replaced without backups. Saved
OAuth credentials, sessions, memories, and other user data are not settings and
are retained. Retired profiles disappear from the profile registry, and their
workspace associations move to the unified profile. The built-in Code Default
profile remains available.

The deploy installs `/usr/local/bin/claude-mode`. Close Code, then run
`claude-mode gateway` or `claude-mode abo`, reopen Code and start a fresh Claude
session. `claude-mode status` prints the current mode. The mode selection is
runtime state and survives redeploys; the configuration itself comes from the
inventory. Its rendered connection data stays in owner-only
`~/.config/infinito/claude.json`.

Gateway mode uses the explicit model picker, independently of gateway discovery.
The default row resolves to the configured model without adding a `[1m]` suffix.
Family-alias background and subagent requests use the explicit background model;
the picker labels local models by their configured names. The output-token budget must
be smaller than the context window. Subscription mode
clears gateway/auth/model overrides in the CLI and the same Code profile and
uses the saved login. Remove conflicting authentication exports from the shell
that starts Claude or Code; repository-local settings and machine-wide managed
policies retain their normal Claude precedence.

The role ships persistent CLI tests under `files/test/` and a `test.env.j2`
entry for the existing CLI harness. A unified-profile deploy also installs and
runs these tests immediately as the workstation user. They check the deployed
settings and use temporary homes to exercise the actual `claude-mode`, Claude
authentication status, native recognition of the deployed Code profile, and
installation of an offline fixture extension into a temporary profile. They also
check the actual SDK model picker, native `/context` output and installed agent
extensions in the deployed profile. They do
not change the real user's
connection mode or making provider requests. Hosts without unified mode report
an explicit skip through the shared harness.
