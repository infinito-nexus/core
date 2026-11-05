# An example brief

Written for Oryn, a desktop file manager (the film is `examples/oryn` in the motion-designer repository). It shows the shape and the level of detail a brief needs. Its title, lines, scenes and closing line belong to Oryn: write new ones for every product.

---

ORYN: FILES, IN MOTION

A launch film for Oryn, the fast, modern file manager.

Show how everyday file work can feel focused, fluid, and surprisingly satisfying. Built as a code-driven motion piece, with no paid templates or stock motion graphics.

<inputs>
Use:
- The Oryn logo and wordmark
- Current screenshots or screen recordings of Oryn, ideally showing dual panes, file transfers, preview, search, and the command palette
- A royalty-free music track with a clear beat, a strong drop, and a quieter breakdown
- Optional desktop or workspace footage for the final shot

Ask me for any missing assets before you begin. Use the real Oryn interface wherever possible; don’t invent features or redesign the product.
</inputs>

<direction>
Create a crisp, confident desktop-app launch film. The motion should feel precise and tactile, like using a fast, well-made tool.

Use a warm neutral canvas, deep ink tones, and restrained accent color drawn from Oryn’s actual interface. Let the real product UI provide the visual detail. Keep typography bold for the wordmark and clear for interface labels.

Build each scene from the one before it. Panels slide, rows assemble, selections travel, and shapes become windows or file cards. Use deliberate cursor movement only when it helps explain an action.

Keep the pacing energetic but readable. Every animation should make the product easier to understand.

Avoid: generic “AI” visuals, fake interface details, excessive glass effects, decorative particles, 3D flips, random cursor movement, and transitions that obscure what changed.
</direction>

<structure>
Open on the Oryn wordmark. Its letters draw together into a single file row. The row expands into the app window.

The window divides into two panes. A folder opens on the left; a destination opens on the right. Files appear in a clean, scannable list. The cursor selects a group and moves them across. A transfer indicator grows smoothly, then resolves into the finished files.

A file tile lifts from the grid and opens into preview: image, code, or document. The preview folds back into the pane, revealing the other view modes and a breadcrumb path.

The search field expands. A query travels through the file list, narrowing it to a few results. The results gather into a selection, then become a batch rename preview.

A command palette opens over the workspace. Type a command, highlight the matching action, and launch it. The palette closes into the next scene.

Show Oryn moving between local and remote files, or into an archive, using only interface elements that exist in the supplied build. Keep the action simple: open, browse, transfer.

The app window pulls back to reveal Oryn on the desktop. End on the wordmark and a short line:

“Your files. In flow.”

Let the final frame connect cleanly to the opening frame.
</structure>

<build>
- Create one square 1440 × 1440 HTML composition.
- Drive every visual state from a deterministic `seek(t)` function so any frame can be rendered directly.
- Use spring-like motion for panels, selections, and transitions; keep movement smooth and controlled.
- Use the provided Oryn screenshots or recordings as the source of truth for the interface.
- Sync key actions to the music’s beat, with the transfer completion landing on the drop.
- Render at 60 fps and inspect the opening, each major product moment, and the ending for visual glitches and unreadable UI.
</build>

<start>
First ask for the Oryn logo, product screenshots or recordings, and music track. Then show me a beat map and four stills: opening, dual-pane transfer, preview/search, and final frame. Wait for feedback before building the full film.
</start>
