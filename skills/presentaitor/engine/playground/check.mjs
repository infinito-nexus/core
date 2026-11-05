import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { openPage } from "../scripts/cdp.mjs";

const [dir, ...names] = process.argv.slice(2);
let failed = 0;
for (const name of names) {
  const page = await openPage(pathToFileURL(join(dir, `${name}.html`)).href, { width: 1440, height: 1100 });
  try {
    const info = await page.evaluate("document.fonts.ready.then(() => ({ dur: FILM.DURATION, P: window.PLAYGROUND.P }))");
    const shots = join(dir, "stills", name);
    mkdirSync(shots, { recursive: true });
    const times = [0.25, 0.5, 0.75].map((k) => +(info.dur * k).toFixed(2));
    for (const t of times) {
      await page.evaluate(`seek(${t})`);
      writeFileSync(join(shots, `t${t.toFixed(2)}.png`), await page.screenshot());
    }
    const again = await page.evaluate(`seek(${times[1]}), document.getElementById("stage").innerHTML`);
    await page.evaluate(`seek(${times[2]})`);
    const pure = again === (await page.evaluate(`seek(${times[1]}), document.getElementById("stage").innerHTML`));
    const ok = !page.errors.length && pure;
    if (!ok) failed++;
    console.log(`${ok ? "PASS" : "FAIL"}  ${name.padEnd(12)} ${times.join(", ")}s${pure ? "" : "  (same t gave a different frame)"}` +
      `${page.errors.length ? "  errors: " + page.errors.join(" | ") : ""}  defaults ${JSON.stringify(info.P)}`);
  } finally {
    await page.close();
  }
}
process.exitCode = failed ? 1 : 0;
