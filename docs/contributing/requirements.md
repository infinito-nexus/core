# Requirements 📋

Requirements live under `docs/requirements/` and define what the project must do.
Their primary purpose is to drive AI-agent-assisted development: a contributor creates a requirement file and then instructs the agent to iterate by following [requirements.md](../agents/action/requirements.md) and [Compose Loop](../agents/action/iteration/compose.md), continuing until every Acceptance Criterion is fulfilled.

Creating a requirement is **not mandatory** to work on a task.
For normal work items, bugs, or feature requests, use the project tools directly:

- Internal planning and work items: [project.infinito.nexus](https://project.infinito.nexus/)
- Bug reports and feature requests: [s.infinito.nexus/issues](https://s.infinito.nexus/issues)

Writing a requirement file is RECOMMENDED when you want an AI agent to autonomously implement and validate a feature end to end, because it gives the agent a structured, checkable definition of done.

## File Naming

Every requirements file MUST follow the pattern `NNN-topic.md`, where `NNN` is a zero-padded three-digit sequence number (e.g. `000-template.md`, `001-auth.md`).

## File Structure

Every requirements file MUST follow this template exactly:

```markdown
# NNN - Title

## User Story

As a <role>, I want <goal> so that <benefit>.

## Acceptance Criteria

- [ ] Criterion one.
- [ ] Criterion two.
```

- The **User Story** MUST follow the "As a / I want / so that" format.
- Each **Acceptance Criterion** MUST be written as a Markdown task list item (`- [ ]`).
- Criteria MUST be independently verifiable, with one observable outcome per item.
- Completed criteria MUST be checked off (`- [x]`) once the corresponding work is merged.

## Cross-linking

- You MUST cross-link from the requirement to any PR or issue that implements it.
- You MUST cross-link from the implementing PR template back to the requirement file.

## See Also

- How agents process requirements: [requirements.md](../agents/action/requirements.md)
