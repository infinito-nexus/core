# Refactoring and Optimization

## After Every Commit

After every commit you MUST ask the user:

> "Do you want to refactor and optimize the affected files?"

- If the user answers **no**, continue without refactoring.
- If the user answers **yes**, follow the steps below.

## Refactoring Steps

1. You MUST re-read `AGENTS.md` and follow all instructions in it before proceeding.
2. You MUST apply all rules from `AGENTS.md` and `docs/contributing/` to every affected file, not only code rules, but also documentation, naming, structure, and any other applicable guidelines.
3. For every affected documentation file, you MUST optimize the text so it follows the standards defined in [documentation.md](../../contributing/documentation.md), including RFC 2119 keywords, link formatting, and writing style.
4. If the change affects an Ansible role, you MUST refactor and optimize the **entire role**, not only the files that were directly modified.
   - If the change affects **more than one role**, you MUST ask the user before proceeding:
     > "The following roles are affected: [list]. Which roles should be refactored, specific ones or all?"
   - Then refactor only the roles confirmed by the user.
