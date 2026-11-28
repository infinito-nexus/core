# Instructions replay 📖

How CI proves that the `### Production` block a role's documentation publishes still deploys that role.

For the workflow catalog see [workflows.md](workflows.md).

## Where it runs 🏗️

The replay rides along on a deploy row of the sweep instead of holding a job of its own. [guide.py](../../../../../utils/roles/guide.py) marks one row per role:

- the role's **smallest variant**, the one whose `meta/variants.yml` overlay enables the fewest services, because that is the shape the instructions describe;
- only when the role is invokable, because that is what makes the documentation build emit a Production block for it;
- only when the guide's own mode (`compose` for a role shipping a container stack, `host` otherwise) is enabled in `meta/services.yml` and not listed under `skip` in `meta/tests.yml`.

The marked row carries `instructions: <mode>` in the matrix JSON, and the plan table names that mode in its 📖 column; its job title is that of an ordinary deploy row.

## What the row does 🚀

The marker adds `web-app-docs` to that row's `apps`, so the documentation is deployed beside the role under test. Its own CLI test then reads the role's page, takes the Production block out of the rendered HTML, and runs it.

One role per deploy, never a list. [guide_role.py](../../../../../plugins/lookup/guide_role.py) names it from `APP_ID`, the row's own app, which [run.py](../../../../../cli/administration/deploy/development/deploy/run.py) forwards into the infinito container where Ansible runs. A deploy that carries no `APP_ID`, or one whose app publishes no Production block, draws an invokable peer of the round at random instead.

Reading the block off the page rather than out of the tree is the point: a reader copies from the site, so that is what has to work. Nothing in the repository is consulted at replay time.

## The target 🎯

The replay deploys onto the stack's shared `target` service, documented in [compose/target](../../../../../compose/target/README.md): a bare systemd and sshd machine that `make compose-up` resets and every round of a development deploy resets again, compose and swarm rounds alike. Only the stack host replays: the `infinito` container in a compose round, the swarm manager in a swarm round. [replay.sh](../../../../../roles/web-app-docs/files/test/replay.sh) reads the root key's path from the `.env` of that host's checkout and the target's address from the `.address` file the last reset wrote beside the key; a missing `.env` fails the test with a pointer to `make dotenv`.

Placeholders (`<your-domain>`, `<your-clearnet-resolver>`, `<your-country>`) are filled from the deployment's own values, and `<your-ssh-public-key>` / `<your-ssh-private-key-file>` from the two halves of the root key the last reset generated at `INFINITO_TARGET_KEY`.

Before it changes anything the replay claims the target with `mkdir /var/lib/infinito-target-claim` over SSH. One target serves one replay per reset, so replays run one after another; a second one on the same target, or a target that refuses the key, fails the test with a pointer to `make compose-target-reset`.

A block whose own `docker run` starts the published deploy image runs on the stack host and deploys into the target over SSH, which is what that recipe describes: a managed server. `HOST` is filled with the address from `INFINITO_TARGET_KEY.address`, and the placeholder guard runs after this fill, not before it.

A role without a container stack publishes the other shape, a host install that configures the machine it runs on. That block is piped into `bash -e -s` on the target over SSH, in the checkout the target mounts at `INFINITO_SRC_DIR`. A block that opens with `git clone` is such a host install: those two lines are dropped and the mounted checkout is used instead, so the replay runs against the tree under test. A block of neither shape fails the test, because nothing tells the harness which of the two machines it addresses.

The target starts from the **distribution base image** `INFINITO_PARENT_IMAGE`, not from an image this project publishes, so the replay also exercises the installation. It carries no container engine of its own: the replayed deploy installs `docker-ce` and restarts `docker.service`, and a target that already ran the distribution's engine fails that restart with `failed to load listeners: no sockets found via socket activation`. Its `/var/lib/docker` is a volume, so the installed daemon lands on a real filesystem.

The target's resolver answers `INFINITO_DOMAIN` and every name under it with the target's own address, so `DOCS_TEST_DOMAIN` has to equal `INFINITO_DOMAIN`; the test fails when it does not.

The deploy reaches `root` over SSH, so a first run needs `PermitRootLogin` to allow it. `SYS_SVC_SSHD_PERMIT_ROOT_LOGIN` defaults to `no`; the published recipe passes `prohibit-password` through the `--vars` JSON it already carries.

## Reading a failure 🔍

The CLI test prints the block it fetched and the output of the replay. The role's own deploy snapshots live in `rescue-diagnostics-<artifact>`.

To reproduce one locally, deploy the role together with the documentation and let the CLI test run:

```bash
APP_ID=<role> make compose-deploy mode=reinstall apps=<role>,web-app-docs full_cycle=false
```
