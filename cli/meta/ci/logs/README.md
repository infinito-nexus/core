# Logs 📥

Download GitHub Actions job logs and run artifacts for a CI run, optionally filtered by job conclusion, for local inspection.

```
python -m cli.meta.ci.logs.download <run-id|run-url> [-s] [-f] [-c] [--skipped] [-d DEST] [-j N]
```

Conclusion flags select which jobs' logs are fetched (`-s`/`--success`, `-f`/`--failed`, `-c`/`--cancelled`, `--skipped`); with none given every completed job is fetched. Logs land under `DEST/logs/`, artifacts under `DEST/artifacts/`. `DEST` defaults to `/tmp/logs/<run-id>`. Job logs are available per job even while the run is still in progress; `--no-logs` / `--no-artifacts` skip either half.

Logs and artifacts download in parallel across `-j`/`--jobs` workers (default: CPU count); each worker waits a random `1`-`2*workers` second jitter before its request so the burst does not trip GitHub API rate limits.
