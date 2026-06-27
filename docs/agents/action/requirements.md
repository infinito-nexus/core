# Requirements

When asked to work on a requirement, you MUST follow this page.

## Reading a Requirement

- You MUST read the full requirement file before writing any code or plan.
- You MUST identify the User Story and every Acceptance Criterion before acting.
- If a criterion is ambiguous, you MUST ask the user to clarify before proceeding.

## Processing

- You MUST treat each unchecked criterion (`- [ ]`) as a discrete unit of work.
- You MUST follow [Compose Loop](iteration/compose.md) for the edit-deploy-validate loop while implementing criteria.
- You MUST NOT mark a criterion as done (`- [x]`) until its behavior is verified end to end.
- You MUST check off each criterion in the requirement file as soon as it is verified. Do not batch them.
- You MUST NOT close or skip a criterion that has not been explicitly verified, even if the implementation looks complete.

## Definition of Done

A requirement is complete when:

- All criteria are checked (`- [x]`).
- The implementing changes are committed and the PR references the requirement file.
