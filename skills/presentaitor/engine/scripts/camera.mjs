import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { openFilm } from "./cdp.mjs";

const [pagePath, out, fpsArg] = process.argv.slice(2);
if (!pagePath || !out) {
  console.error("usage: camera.mjs <page.html> <out.json> [fps]\n" +
    "  samples window.FOOTAGE_CAMERA(t) -> {x, y, s} (film pixels) once a frame, for footage.py --camera");
  process.exit(2);
}
const { page, info } = await openFilm(resolve(pagePath));
try {
  const fps = Number(fpsArg) || info.FPS;
  const n = Math.round((info.frames / info.FPS) * fps);
  const has = await page.evaluate("typeof window.FOOTAGE_CAMERA === 'function'");
  const cams = has
    ? await page.evaluate(`Array.from({ length: ${n} }, (_, i) => { const c = window.FOOTAGE_CAMERA(i / ${fps}); return [+c.x.toFixed(2), +c.y.toFixed(2), +c.s.toFixed(4)]; })`)
    : null;
  writeFileSync(out, JSON.stringify({ W: info.W, H: info.H, fps, frames: cams }));
  console.log(`${out}: ${has ? `${n} camera samples` : "no FOOTAGE_CAMERA on the page"}`);
} finally {
  await page.close();
}
