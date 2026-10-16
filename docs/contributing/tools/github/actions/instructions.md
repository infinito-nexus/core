# Instructions replay 📖

How CI proves that the `### Production` block a role's documentation publishes still deploys that role.

For the workflow catalog see [workflows.md](workflows.md).

## Where it runs 🏗️

The replay rides along on a deploy row of the sweep instead of holding a job of its own. [guide.py](../../../../../utils/roles/guide.py) marks one row per role:

- the role's **smallest variant**, the one whose `meta/variants.yml` overlay enables the fewest services, because that is the shape the instructions describe;
- only when the role is invokable, because that is what makes the documentation build emit a Production block for it;
- only when the guide's own mode (`compose` for a role shipping a container stack, `host` otherwise) is enabled in `meta/services.yml` and not listed under `skip` in `meta/tests.yml`.

The marked row carries `instructions: <mode>` in the matrix JSON and a 📖 in its job title, between the variant number and the ⭐ of a priority row.

## What the row does 🚀

The marker adds `web-app-docs` to that row's `apps`, so the documentation is deployed beside the role under test. Its own CLI test then reads the role's page, takes the Production block out of the rendered HTML, and runs it.

One role per deploy, never a list. [guide_role.py](../../../../../plugins/lookup/guide_role.py) names it from `APP_ID`, the row's own app, which [run.py](../../../../../cli/administration/deploy/development/deploy/run.py) forwards into the infinito container where Ansible runs. A deploy that carries no `APP_ID`, or one whose app publishes no Production block, draws an invokable peer of the round at random instead.

Reading the block off the page rather than out of the tree is the point: a reader copies from the site, so that is what has to work. Nothing in the repository is consulted at replay time.

## The machine 🐳

Placeholders (`<your-domain>`, `<your-clearnet-resolver>`) are filled from the deployment's own values, and `<your-ssh-public-key>` / `<your-ssh-private-key-file>` from an ed25519 pair generated per run under `DOCS_TEST_WORK`.

The block runs on the stack host and deploys into a throwaway target container, which is what the published recipe describes: a managed server reached over SSH. [machine.sh](../../../../../roles/web-app-docs/files/test/machine.sh) brings that target up through [files/test/compose.yml](../../../../../roles/web-app-docs/files/test/compose.yml) under the project `docs-guide-<role>`, and tears it down with `down -v --rmi local`.

`HOST` is filled with the target's own bridge address, resolved once the container is up. The target joins the default bridge so the recipe's nested `docker run` can reach it; that bridge has no DNS, so the value must be an address rather than a name. The placeholder guard therefore runs after this fill, not before it.

The machine starts from the **distribution base image**, not from an image this project publishes, so the replay also exercises the installation. `MACHINE_BASE_IMAGE` is read as `INFINITO_PARENT_IMAGE` out of the `.env` of the mounted checkout, where the env layer has already composed it from the [meta/distros.yml](../../../../../meta/distros.yml) SPOT and honoured any `custom.env` override. A missing `.env` fails the test with a pointer to `make dotenv`. The one build step of [files/test/Dockerfile](../../../../../roles/web-app-docs/files/test/Dockerfile) runs [init.sh](../../../../../roles/web-app-docs/files/test/init.sh), which returns immediately when the base already carries `/sbin/init`.

The target receives nothing but an ssh server before the replay. [sshd.sh](../../../../../roles/web-app-docs/files/test/sshd.sh) installs one, authorizes the run's public key for `root`, and `machine.sh` waits for it to answer. Everything else arrives through the deploy, which is the claim under test.

The target carries no container engine of its own. The replayed deploy installs `docker-ce` and restarts `docker.service`; a target that already ran the distribution's engine fails that restart with `failed to load listeners: no sockets found via socket activation`, because the running `docker.socket` belongs to the package being replaced. Keeping the target bare removes the collision instead of working around it. Its `/var/lib/docker` is a named volume so the installed daemon lands on a real filesystem rather than stacking `fuse-overlayfs` on `fuse-overlayfs`.

The deploy reaches `root` over SSH, so a first run needs `PermitRootLogin` to allow it. `SYS_SVC_SSHD_PERMIT_ROOT_LOGIN` defaults to `no`; the published recipe passes `prohibit-password` through the `--vars` JSON it already carries.

The block is replayed once systemd reports `running` or `degraded`. A block that opens with `git clone` is a host install: those two lines are dropped and the mounted checkout is used instead, so the replay runs against the tree under test.

## Reading a failure 🔍

The CLI test prints the block it fetched and the output of the replay. The role's own deploy snapshots live in `rescue-diagnostics-<artifact>`.

To reproduce one locally, deploy the role together with the documentation and let the CLI test run:

```bash
APP_ID=<role> make compose-deploy mode=reinstall apps=<role>,web-app-docs full_cycle=false
```
