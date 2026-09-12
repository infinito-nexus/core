# Instructions replay 📖

How CI proves that a role README's `### Production` block still deploys the role.

For the workflow catalog see [workflows.md](workflows.md).

## Where it runs 🏗️

The replay rides along on a deploy row of the sweep instead of holding a job of its own. `utils/roles/guide.py` marks one row per role:

- the role's **smallest variant**, the one whose `meta/variants.yml` overlay enables the fewest services, because that is the shape the README describes;
- only when the README carries a `### Production` heading;
- only when the guide's own mode (`compose` for a role shipping a container stack, `host` otherwise) is enabled in `meta/services.yml` and not listed under `skip` in `meta/tests.yml`.

The marked row carries `instructions: <mode>` in the matrix JSON and a 📖 in its job title, between the variant number and the ⭐ of a priority row.

## What the row does 🚀

`.github/workflows/call-test-deploy.yml` runs the replay as the job's last step, after the row's own deploy and after the swarm teardown: the replay deploys the role a second time and needs the runner's ports. It calls `scripts/tests/deploy/distros.sh scripts/github/guide/one.sh` with `GUIDE_ROLE` set to the row's app and `GUIDE_MODE` to the mode the marker carries, which is independent of the deploy mode the rotation gave the row. A swarm row therefore still replays a `compose` guide.

A red deploy skips the replay: the step carries no `always()`, so the runner state a failed deploy leaves behind never reaches the guide.

## Reading a failure 🔍

The replay writes its rescue snapshots under `INFINITO_RESCUE_DIAGNOSTICS_BASE/<distro>/<role>`, uploaded as `rescue-diagnostics-instructions-<artifact>`. The deploy's own snapshots live in `rescue-diagnostics-<artifact>`.

To reproduce one locally, export `GUIDE_ROLE`, `GUIDE_MODE`, `INFINITO_DISTRO` and run `scripts/github/guide/one.sh`.
