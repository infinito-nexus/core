# Agent action guides 🧭

This directory contains action-oriented runbooks for agent work.
Its scope is how agents should develop, debug, test, refactor, commit, and handle pull requests while staying aligned with repository policy.

Unlike the rest of `docs/agents/`, these files are read on demand rather than at session start: an `i8-` skill routes to the runbook of the action it covers, and an agent performing one of these actions without a skill reads that runbook first. They are the bulk of the agent documentation and each one is inert until its action is the task.
