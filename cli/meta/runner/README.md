# Runner Pool 🏃

Commands that size and report the local runner pool: `count` prints the default number of pool runners and the RAM, CPU and disk terms it is the minimum of, and `cleanup` (behind `make runner-cleanup-report`) prints every held job with its age and every svc-runner job stack the infra runner's Docker lists that no running or held job owns, removing nothing.
