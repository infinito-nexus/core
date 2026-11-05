# Harness

The skill is written for any coding agent that can run a shell, read files and look at images: Claude Code, Codex,
or another. Where a step names an action below, use your own tool for it. Everything else (the scripts, the film
folder, the checks) is the same everywhere.

## The actions

| Action | Claude Code | Codex | Anything else |
|---|---|---|---|
| **SKILL_DIR**: where the scripts are | `${CLAUDE_SKILL_DIR}`, already written out in SKILL.md | the folder of the `SKILL.md` you opened | the same |
| **Plan**: present the brief, wait for a yes | `EnterPlanMode`, read, write the brief, then `ExitPlanMode` with it | write the brief as the plan in chat, ask for approval, and stop | the same |
| **Ask**: one decision only the user can make | `AskUserQuestion` | a plain question in chat, then stop | the same |
| **Look**: see a PNG | `Read` the file | `view_image` | open the file the way your tools allow |
| **Delegate**: hand a role to a helper with a clean context | the `Agent` tool, several in one message so they run together | its subagent tools, which may only appear after a tool search, so search for them at the start of the run; once the user agreed, use them from the first review on; otherwise `codex exec` with the same prompt | a headless run of your own CLI; with none, do the role yourself, inline |
| **Background**: run a long command and keep working | `Bash` with `run_in_background` | `nohup <cmd> > out/<name>.log 2>&1 &` | the same |
| **Send**: give the user a finished file | `SendUserFile` where it exists, else the path | the path, and `open <file>` on a Mac when they want to watch | the path |

Use `$SKILL_DIR` in the reference files as that folder's absolute path: each shell call starts fresh, so write the
path out in every command rather than exporting it once.

## Delegating

A helper never sees this conversation, the skill or your memory. Its prompt is the **whole role file** (for
example [reviewer](reviewer.md)) followed by a `## Dispatch` block with everything the role asks for, as absolute
paths and plain values. The helper writes its result to the file the dispatch names, and that file is how you
know it finished: when a helper ends and its file is missing, start it once more with the same prompt, then do
the work yourself.

Helpers that touch different time ranges are independent; start them together. A harness limit on how many run at
once changes how many start together, never how much gets reviewed.

On Codex, delegating needs the user's go-ahead. Ask once, in the same message that presents the brief, and treat a
standing grant in `AGENTS.md` as a yes.

## Waiting

Wait for a file, not a message. A render in the background is done when the script prints its last line to the
log and the `.mp4` exists; check that once, when you have nothing else to do, rather than polling every few seconds.
