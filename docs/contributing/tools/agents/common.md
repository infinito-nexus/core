# Agent Guidelines for humans

AI assistants are welcome, but they MUST follow the same workflow as humans.

- You MUST treat [AGENTS.md](../../../../AGENTS.md) as the single, runtime-agnostic source of agent-specific execution instructions. There are no tool-specific extension files.
- You MUST NOT invent commands, workflows, or files that do not exist.
- You MUST NEVER expose secrets in prompts, code, screenshots, or logs.
- You MUST treat AI output as a draft that must be reviewed for wrong assumptions, duplicate logic, and security mistakes.
- You MUST keep explanations simple and explicit.
- You MUST state assumptions clearly.

For a full reference of permitted Claude Code operations and their security rationale, see [claude/](claude/README.md).

For further support, visit the AI forum at [s.infinito.nexus/aihub](https://s.infinito.nexus/aihub) or join the Matrix group #ai:infinito.nexus.
