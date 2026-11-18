# Ansible Plugins (`plugins/`) 🧩

This document is the central reference for plugin types and plugin placement in Infinito.Nexus.

> **Not to be confused with application addons.**
> This `plugins/` directory holds **Ansible** plugins (action / filter / lookup) that extend the automation engine itself.
> Some applications *also* call their own extensions "plugins" (e.g. Nextcloud, WordPress).
> Those application-level extensions, whatever the app calls them natively, are declared through the unified `meta/addons/` contract, documented in [Unified Addons](../docs/contributing/design/role/services/layout.md#unified-addons-metaaddons-).
> An app "plugin" is an *addon*; an Ansible plugin lives here.

## Current Project Layout 🗂️

```text
plugins/
├── action/       # custom action plugins
├── connection/   # custom connection plugins
├── filter/       # custom Jinja2 filters
└── lookup/       # custom lookup plugins
```

Configured plugin paths in this repository are defined in `ansible.cfg`:

- `action_plugins = ./plugins/action`
- `connection_plugins = ./plugins/connection`
- `filter_plugins = ./plugins/filter`
- `lookup_plugins = ./plugins/lookup`

## All Common Ansible Plugin Types 📚

The table below summarizes common Ansible plugin types and their conventional directory names.

| Emoji | Plugin Type | Conventional Directory | Purpose |
| --- | --- | --- | --- |
| ⚙️ | `action` | `action_plugins/` or `plugins/action/` | Wrap/extend module execution behavior at task runtime. |
| 🔐 | `become` | `become_plugins/` | Implement privilege escalation methods. |
| 💾 | `cache` | `cache_plugins/` | Persist gathered facts and cached data between runs. |
| 📣 | `callback` | `callback_plugins/` | React to play/task events (logging, reporting, notifications). |
| 🖧 | `cliconf` | `cliconf_plugins/` | Define CLI command transport behavior (mainly network platforms). |
| 🔌 | `connection` | `connection_plugins/` | Control how Ansible connects to targets (ssh, local, etc.). |
| 🔍 | `filter` | `filter_plugins/` or `plugins/filter/` | Add Jinja2 filters for data transformation. |
| 🌐 | `httpapi` | `httpapi_plugins/` | API transport layer over HTTP(S), mainly for network devices. |
| 🧭 | `inventory` | `inventory_plugins/` | Build dynamic inventories from APIs, services, or files. |
| 👉 | `lookup` | `lookup_plugins/` or `plugins/lookup/` | Resolve dynamic values during playbook processing. |
| 🛰️ | `netconf` | `netconf_plugins/` | NETCONF transport integration for network automation. |
| 🐚 | `shell` | `shell_plugins/` | Adjust shell command wrapping/execution behavior. |
| 🧠 | `strategy` | `strategy_plugins/` | Customize task scheduling/execution strategy. |
| ✅ | `test` | `test_plugins/` | Add Jinja2 tests used in conditions and templates. |
| 📦 | `vars` | `vars_plugins/` | Load variables from custom sources. |

## Which Plugin Type to Use 🧭

### `action` ⚙️

Use when task execution behavior itself must be changed or wrapped.

Examples:

- centralized retry logic (`uri_retry.py`),
- argument normalization before module dispatch,
- pre/post task orchestration.

### `filter` 🔍

Use for pure data transformation in Jinja2 expressions.

Examples:

- mapping/normalizing dictionaries,
- deriving computed fields for templates,
- deterministic formatting helpers.

### `lookup` 👉

Use when a value must be dynamically resolved at runtime.

Examples:

- computing IDs from role metadata,
- resolving paths/version data,
- reading structured project data for templates/tasks.

### `callback` 📣

Use to hook into execution events and shape output/reporting.

### `inventory` 🧭

Use when host/group data should come from a dynamic source.

### `strategy` 🧠

Use to alter how tasks are scheduled/executed across hosts.

### `vars` 📦

Use to load variables from custom backends.

### `connection`, `become`, `shell` 🔌🔐🐚

Use to customize low-level execution and privilege mechanics.

### `cache` 💾

Use to persist facts/results across runs for performance and consistency.

### `cliconf`, `httpapi`, `netconf` 🖧🌐🛰️

Use in network automation contexts requiring protocol-specific transport behavior.

### `test` ✅

Use to add custom Jinja2 test operators for conditional logic.

## Best Practices 🧪

- Keep plugin interfaces explicit and stable.
- Keep plugin logic focused; move shared logic to `utils/`.
- Add unit tests for plugin behavior and integration tests for end-to-end flows.
- Prefer deterministic outputs and avoid hidden global state.
- Document any plugin-specific task arguments in the plugin docstring and README.

## References 🔗

- Ansible plugin development: [docs.ansible.com](https://docs.ansible.com/ansible/latest/dev_guide/developing_plugins.html)
- Ansible plugin index (all types): [docs.ansible.com](https://docs.ansible.com/ansible/latest/plugins/plugins.html)
- Ansible `ansible-doc` plugin types: `ansible-doc -t ...`
