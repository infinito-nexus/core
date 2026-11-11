# Agent Instructions Pull Request

## Summary

Briefly describe the change to the agent instruction files and the expected effect.

Examples:

* Add a new repository rule to `AGENTS.md`
* Fix contradictory guidance between `AGENTS.md` and `docs/agents/*`
* Improve instruction clarity for `AGENTS.md`

---

## Template Type

Select the primary intent of this PR:

* [ ] **Feature** - Adds or extends agent guidance or workflow support
* [ ] **Fix** - Repairs incorrect, unclear, or conflicting agent guidance

---

## Affected Files

List the touched agent instruction files.

* [ ] `AGENTS.md`
* [ ] `roles/<role>/AGENTS.md`
* [ ] `docs/agents/*`

Additional notes:

* Any other related instruction or documentation files:

---

## Change Type

Select the semantic version impact of this change:

* [ ] **Major** - Breaking change
* [ ] **Minor** - New backwards-compatible feature
* [ ] **Patch** - Small improvement or compatible adjustment

---

## Change Details

Explain what changed and why.

Key points:

* What instruction, workflow, or policy changed?
* Why is this guidance needed or why was the previous guidance insufficient?
* How does this interact with `AGENTS.md` as the repository-wide source of truth?
* Which alternatives were considered?

---

## Validation

Describe how the instruction change was validated.

* [ ] Conflicting or ambiguous guidance checked
* [ ] Consistency between `AGENTS.md`, `roles/<role>/AGENTS.md`, and `docs/agents/*` verified
* [ ] Examples, workflows, or affected contributor paths reviewed

---

## Security Impact

Indicate whether this change has security implications.

* [ ] No relevant security impact
* [ ] Security impact present

If security impact is present, explain:

* Affected permissions, destructive actions, secrets, or safety guardrails:
* Risk reduction, new exposure, or compatibility considerations:
* Security-specific validation performed:

---

## Review Focus

Help reviewers focus on the riskiest parts of this PR.
For repository-wide contribution and review expectations, see [CONTRIBUTING.md](../../CONTRIBUTING.md).

* Highest-risk instructions, assumptions, or policy changes:
* Cross-file consistency or contradiction concerns:
* Specific feedback requested from reviewers:

---

## Definition of Done (DoD)

* [ ] The implementation follows the Definition of Done, and the contribution guidelines in [CONTRIBUTING.md](../../CONTRIBUTING.md) were considered and applied during implementation.

---

## Additional Notes

Add any reviewer context for rollout, policy interpretation, or follow-up work.
