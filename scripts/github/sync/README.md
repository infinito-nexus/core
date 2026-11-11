# GitHub Sync Helpers 🔄

[main_from_repository.sh](main_from_repository.sh) force-pushes the source repository's `main` onto the current repository's `main`. The `🔄 Sync main` job of [entry-push-latest.yml](../../../.github/workflows/entry-push-latest.yml) runs it on every push.

The push needs the secret `CI_SYNC_MAIN_TOKEN`, see [secrets.md](../../../docs/contributing/tools/github/actions/secrets.md). The source repository and the switch to disable the sync are the repository variable `CI_SYNC_MAIN_SOURCE_REPOSITORY`, see [configuration.md](../../../docs/contributing/tools/github/actions/configuration.md).
