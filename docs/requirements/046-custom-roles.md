# 046 - Custom Roles from Inventory-Declared Sources

## User Story

As an operator, I want to declare application roles that live in their own repositories, such as the landing page and the store GUI, as ordinary inventory groups that Infinito.Nexus pulls into `roles/web-app-cst-*` and verifies like every in-tree role, so that these projects ship their role from their own repository without a fork of core and without a second, weaker set of checks.

## Acceptance Criteria

### Declaration

- [ ] A custom role is an ordinary inventory group named `web-app-cst-<name>`; a host joins it the same way it joins any `web-app-*` group.
- [ ] `applications.web-app-cst-<name>.custom: true`, set in `host_vars` or anywhere else the inventory sets application values, marks the group as a custom role.
- [ ] `applications.web-app-cst-<name>.source` holds `url` (a Git URL over HTTPS or SSH), `version` (a tag or a full commit SHA) and `path` (the role directory inside that repository).
- [ ] A custom role whose `source.version` names a branch, or whose `source` misses `url`, `version` or `path`, stops the run before anything is pulled, and the message names the group and the missing or rejected field.
- [ ] A group named `web-app-cst-*` without `custom: true`, or `custom: true` on a group outside the `web-app-cst-` prefix, stops the run with a message naming the group.
- [ ] The pull reads `custom` and `source` from the raw inventory and never renders them as templates: a value that holds a Jinja expression stops the run with a message naming the group and the field, so no templated value can trigger a fetch.
- [ ] A `source.url` that embeds credentials stops the run without echoing the URL.

### Authentication

- [ ] A private repository is fetched through the SSH agent or SSH configuration of the controller.
- [ ] A fetch that needs interactive credentials fails instead of prompting.
- [ ] No credential reaches the inventory, the `ansible-playbook` command line, Ansible variables or the deploy log.

### Pull and placement

- [ ] Before the playbook starts, and so before the applications SPOT reads `roles/*/meta/`, the deploy pulls every custom role declared for the target hosts at its `source.version` and places `source.path` as `roles/web-app-cst-<name>` in the core checkout that runs the deploy.
- [ ] A `make` target pulls the custom roles an inventory declares into the local core checkout without deploying, so every other `make` target can run against them.
- [ ] A local directory may stand in for `source.url` during development, so a role checkout is verified and deployed without a tag.
- [ ] A local source that resolves to its own placement directory `roles/web-app-cst-<name>` stops the run with a message naming the path, so a pull never deletes its own source.
- [ ] A placed role whose directory name or `vars/main.yml` `application_id` differs from its group name stops the run with a message naming both values; core never renames a role.
- [ ] Pulling again replaces each `roles/web-app-cst-*` directory with the pinned content, and removes the directory of a custom role the inventory no longer declares.
- [ ] A pull that stops leaves `roles/` unchanged, and no staging or leftover directory of a pull appears under `roles/`.
- [ ] A declared name that meets a symbolic link under `roles/`, or a directory the pull did not place, stops the run with a message naming it, and the pull never replaces or removes such a directory.
- [ ] A command lists the placed custom roles with their source and resolved commit, and a `make` target removes every `roles/web-app-cst-*` directory and nothing else.
- [ ] `INFINITO_EXTRA_MOUNTS=<dir>[,<dir>]` mounts each directory read-only at the same path into the `infinito` container when the stack is created, so a local `source.url` resolves inside the container; an entry that is not an existing absolute directory stops the stack start with an error naming it.
- [ ] `roles/web-app-cst-*` is ignored by Git in core, so a pulled role never enters a core commit.
- [ ] The `web-app-cst-` prefix is reserved: a lint fails on an in-tree role whose name starts with it.
- [ ] `meta/categories.yml` declares `web-app-cst` as a category, so the entity name of `web-app-cst-<name>` is `<name>` and the container, database and volume names a custom role derives stay what they were before its rename.
- [ ] A custom role whose entity name equals the entity name of an in-tree role stops the run with a message naming both roles.
- [ ] A swarm or Act run (`make swarm-*`, `make act-*`) carries the pulled custom roles into the copy of the core checkout its nodes use.

### Verification

- [ ] A pulled custom role is scanned by `make test`, `make lint` and `make quality-high` exactly like an in-tree role: no lint, unit or integration check skips `roles/web-app-cst-*`, and no check exists only for custom roles. The one exception is the licence: a custom role is exempt from the Infinito.Nexus licence wording the role README lint demands in Credits, and states its own licence instead.
- [ ] `make compose-deploy` deploys a pulled custom role through the same path as an in-tree role, including its Playwright specs.
- [ ] The README of `php-landingpage` and of `infinito-nexus-gui` documents the inventory format above for their role.
- [ ] `php-landingpage` names its role `web-app-cst-<name>` in directory and `application_id`, and its CI pulls the role into a core checkout and runs core's `make test` and `make lint` against it.
- [ ] `infinito-nexus-gui` names its store role `web-app-cst-<name>` in directory and `application_id`, and its CI pulls the role into a core checkout and runs core's `make test` and `make lint` against it.

### Quality

- [ ] The pull, placement, validation and cleanup logic has unit tests, including a branch name refused as `source.version`, a role whose `application_id` differs from its group, and the removal of a role the inventory no longer declares.
- [ ] `make test` passes.
