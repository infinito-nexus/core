# Capturing a real web UI

For apps whose interface is HTML (Tauri, Electron, web apps) the most faithful film uses the app's own frontend, not a redrawing of it. The film only moves the camera, the pointer and the timing. `examples/oryn` does this for a Tauri file manager; its `tools/` folder is a worked implementation.

## Pipeline

1. **Build the production frontend** from the working tree the user wants shown (e.g. `npx vite build --outDir <film>/app-dist`). Never modify the app's sources for the film.
2. **Mock the backend.** Replace the IPC bridge (Tauri `invoke`, Electron `ipcRenderer`, `fetch` to the API) with a script that answers from fixture data: a fictional file tree, fictional accounts, fictional history. Keep the mock beside the film, not in the app.
3. **Drive the UI to each state** in headless Chrome through the app's own controls (click the sidebar, open the context menu, type in the palette) exactly as a user would. Wait for the UI to settle.
4. **Capture each state**: the DOM (`outerHTML`) and the CSS in effect, with images and fonts inlined, into a JSON bundle.
5. **Mount states in the film**: each state renders in a sandboxed document (an `iframe` with `srcdoc`, or a shadow root) inside the window. `apply(t)` picks the state for `t` and moves elements between states (selection, rows, overlays) with the same springs as any other scene.
6. **Keep zoomed text crisp**: Chrome keeps the raster scale it picked for an iframe's layers while the camera zooms, so sequential seeks drift soft. Re-create the app document for every rendered frame (`remount(t)`). It is slower and worth it.

## Rules

- Every visible feature exists in the build you captured, and behaves as shown. Features behind flags or settings appear as turned on by the user, not as defaults.
- Data is fictional: file names, paths, hosts, users, commits.
- The capture tools, mock and bundle live in the film folder (keep the film folder out of the app's git history, e.g. under an ignored `tmp/`).
- Re-capture when the app changes; never hand-edit a captured bundle into a feature it doesn't have.
