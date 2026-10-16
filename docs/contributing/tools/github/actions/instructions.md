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

Placeholders (`<your-domain>`, `<your-ssh-public-key>`, `<your-clearnet-resolver>`) are filled from the deployment's own values, `HOST` is forced to `localhost`, and `-it` is dropped.

The block then runs inside a throwaway machine, never on the stack host itself. [machine.sh](../../../../../roles/web-app-docs/files/test/machine.sh) brings it up through [files/test/compose.yml](../../../../../roles/web-app-docs/files/test/compose.yml) under the project `docs-guide-<role>`, and tears it down with `down -v --rmi local`.

The machine starts from the **distribution base image**, not from an image this project publishes, so the replay also exercises the installation. `MACHINE_BASE_IMAGE` is read as `INFINITO_PARENT_IMAGE` out of the `.env` of the mounted checkout, where the env layer has already composed it from the [meta/distros.yml](../../../../../meta/distros.yml) SPOT and honoured any `custom.env` override. A missing `.env` fails the test with a pointer to `make dotenv`. The one build step of [files/test/Dockerfile](../../../../../roles/web-app-docs/files/test/Dockerfile) runs [init.sh](../../../../../roles/web-app-docs/files/test/init.sh), which returns immediately when the base already carries `/sbin/init`.

Once the machine is up, the repository checkout mounted into it is prepared with [scripts/tests/workspace/base/01_install.sh](../../../../../scripts/tests/workspace/base/01_install.sh), the same step the workspace suite uses: system packages through `INFINITO_PACKAGE_INSTALL_SCRIPT`, then `make install`. Only then is the block replayed, so it meets a machine prepared exactly the way the documentation tells a reader to prepare one.

One service serves both block shapes: both need `/sbin/init` as the entrypoint and the cgroup mount, and a containerised block additionally needs a work directory mounted at the same absolute path on both sides so the bind sources it names resolve on the daemon.

The container engine is not part of that image. [engine.sh](../../../../../roles/web-app-docs/files/test/engine.sh) installs and starts one inside the running machine, and [machine.sh](../../../../../roles/web-app-docs/files/test/machine.sh) pipes it in only for a block that nests a `docker run`, which needs a daemon before the deploy inside it installs anything. A host install must not get it: `sys-svc-container` replaces the engine with `docker-ce` and restarts `docker.service`, and that restart fails with `failed to load listeners: no sockets found via socket activation` when the running `docker.socket` belongs to the distribution package being replaced. Such a machine gets its engine from the deploy itself.

The block is replayed once systemd reports `running` or `degraded`. A block that opens with `git clone` is a host install: those two lines are dropped and the mounted checkout is used instead, so the replay runs against the tree under test.

## Reading a failure 🔍

The CLI test prints the block it fetched and the output of the replay. The role's own deploy snapshots live in `rescue-diagnostics-<artifact>`.

To reproduce one locally, deploy the role together with the documentation and let the CLI test run:

```bash
APP_ID=<role> make compose-deploy mode=reinstall apps=<role>,web-app-docs full_cycle=false
```
