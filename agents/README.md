# agents/

Every AI agent of the platform is defined here: team agents, the profiles users
start from Open WebUI, n8n and Flowise, the robot and the coding agents. One
tree, one runtime contract, one firewall.

## Layout

- `SOUL.md` the shared base persona every role extends.
- `roles/<role>/` one directory per role: `AGENTS.md` (operating rules),
  `SOUL.md` (persona, opens with `## Objective`), `agent.yml` (machine-readable
  fields), `cron.yml` (scheduled starts, a list that may be empty).
- `skills/` Markdown skills. A skill may build on routines, named in its
  frontmatter `routines`. A skill without routines is a pure rule skill.
- `routines/` a Python package, one LangGraph graph per routine. Deterministic
  steps call the repository's own logic in `cli/` and `utils/`.
- [firewall/](firewall/README.md) RBAC roles with `allow`, `ask` and `deny` rules, plus declared
  account providers under [firewall/providers/](firewall/providers/README.md).
- [scenarios/](scenarios/README.md) one verification scenario per acceptance criterion.

## Model

An agent is a role. A role has one soul with one `## Objective`, runs one or
more skills, and each skill builds on zero or more routines. Work flows top
down: a role runs skills, a skill builds on routines, a routine calls `cli/`
and `utils/`. A routine never calls a skill, a skill never calls a role.

## Routines

- `python -m agents.routines show <routine>` prints the ordered steps and the
  Mermaid diagram, for an interactive agent to follow by hand.
- `python -m agents.routines run <routine>` executes the routine as a graph.

## Configuration

Every field of `agent.yml` and every entry of `cron.yml` is overridable from
the inventory under `agents.<role>`, deep-merged over the role's files. Every
consumer reads the merged result through `lookup('agent_config', role, path)`,
never the raw files.
