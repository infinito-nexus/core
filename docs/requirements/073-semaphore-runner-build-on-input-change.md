# 073 - Semaphore Runner Build on Input Change

## User Story

As an operator iterating on one application, I want a deploy to build the Semaphore runner image only when Semaphore's own round needs it or its inputs changed, so that a deploy of an unrelated application on a stack with Semaphore does not spend minutes and gigabytes rebuilding the runner.

## Decisions (2026-11-01)

1. Today the runner image of `web-app-semaphore` is built from `SOFTWARE_IMAGE:SOFTWARE_IMAGE_TAG` plus the `semaphore` binary of the server image ([files/runner/Dockerfile](../../roles/web-app-semaphore/files/runner/Dockerfile)), and on a development stack that base image is the checkout built as `dev-<git-sha>`. Every deploy that pulls Semaphore in as a provider rebuilds both for each new commit, measured at about 375 s and 7 GB per application deploy.
2. In Semaphore's own round, the runner stays the image of that deploy, as decided on 2026-10-31.
3. Only the runner rebuild changes; the Semaphore server, its project convergence and the app-control path stay as they are.

## Acceptance Criteria

- [ ] A deploy in which `web-app-semaphore` takes part only as a provider of another application builds neither the runner image nor its base image and keeps the runner that is already running.
- [x] A deploy whose round includes `web-app-semaphore` itself builds the runner from the image of that deploy, so the foreign-server deploy and the app-control templates run the checkout of that deploy.
- [x] The runner is also rebuilt when its own inputs changed since the running image: the runner Dockerfile, its build arguments, or the pinned Semaphore server image.
- [x] Replaced runner and base images of earlier commits are removed after a deploy that replaced them, so a series of deploys does not accumulate one base image per commit.
- [x] With `STORAGE_CONSTRAINED`, the storage prune of `sys-svc-compose` spares the runner base image through the `CONTAINER_PRUNE_KEEP_LABEL` label, so the runner build of the same deploy still finds it.
- [ ] A redeploy of an unrelated application with `mode=update` on a stack with Semaphore is at least 300 s faster than before and leaves the free disk space unchanged within 1 GB, measured by the deploy's task profile and `df` before and after.
- [x] A unit test asserts the build decision for the provider-only round, the own round and a changed runner input.
- [x] `roles/web-app-semaphore/README.md` states when the runner is built and which image it runs.
