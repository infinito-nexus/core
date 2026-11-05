import { readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { openFilm } from "./cdp.mjs";

const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = args.indexOf(name);
  if (i < 0) return fallback;
  const [, value] = args.splice(i, 2);
  return value;
};
const has = (name) => {
  const i = args.indexOf(name);
  if (i >= 0) args.splice(i, 1);
  return i >= 0;
};
const dist = flag("--dist", null);
const step = Number(flag("--step", 0.05));
const loop = !has("--no-loop");
if (!args[0]) {
  console.error("usage: check.mjs <page.html> [--dist single.html] [--no-loop] [--step 0.05]");
  process.exit(2);
}

let failed = 0;
const report = (ok, what) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failed++;
};
const firstLine = (e) => String(e.message || e).split("\n")[0];

async function open(path) {
  try {
    return await openFilm(resolve(path));
  } catch (e) {
    report(false, `${path} loads and seeks: ${firstLine(e)}`);
    return null;
  }
}

const CLOCKS = [
  [/Math\.random\s*\(/, "Math.random()"], [/Date\.now\s*\(|new Date\(\s*\)|performance\.now\s*\(/, "the wall clock"],
  [/\b(setTimeout|setInterval|requestAnimationFrame)\s*\(/, "a timer"],
  [/\b(transition|animation)(-[a-z-]+)?\s*:|@keyframes/, "a CSS transition or animation"],
];
const findings = [];
const folder = dirname(resolve(args[0]));
for (const name of readdirSync(folder).filter((f) => /\.(js|css|html)$/.test(f) && f !== "main.js")) {
  readFileSync(join(folder, name), "utf8").split("\n").forEach((line, i) => {
    if (line.length > 2000) return;
    for (const [re, what] of CLOCKS) if (re.test(line)) findings.push(`${name}:${i + 1} ${what}`);
  });
}
report(!findings.length, `no clock, timer, randomness or CSS animation in ${basename(folder)}/` +
  (findings.length ? ` (${findings.length}: ${findings.slice(0, 4).join(", ")})` : ""));

const film = await open(args[0]);
if (film) {
  const { page, info } = film;
  const shot = async (p, t) => {
    await p.evaluate(`seek(${t})`);
    return p.screenshot();
  };
  const compare = async (what, fn) => {
    try {
      report(await fn(), what);
    } catch (e) {
      report(false, `${what}: ${firstLine(e)}`);
    }
  };
  const end = (info.frames - 1) / info.FPS;
  try {
    const thrown = [];
    for (let t = 0; t <= end + 1e-9; t += step) {
      try {
        await page.evaluate(`seek(${t.toFixed(4)})`);
      } catch (e) {
        thrown.push(`${t.toFixed(2)}s ${firstLine(e)}`);
      }
    }
    const errors = [...thrown, ...page.errors];
    report(!errors.length, `every ${step}s from 0 to ${end.toFixed(2)}s without page errors` +
      (errors.length ? ` (${errors.length}, first: ${errors[0]})` : ""));

    const probes = [0, end * 0.23, end * 0.51, end * 0.77, end];
    let differs = [];
    await compare("frames are the same whatever order they are sought in", async () => {
      const inOrder = [];
      for (const t of probes) inOrder.push(await shot(page, t));
      for (const k of [3, 0, 4, 1, 2]) if (!(await shot(page, probes[k])).equals(inOrder[k])) differs.push(probes[k].toFixed(3) + "s");
      return !differs.length;
    });
    if (differs.length) console.log(`      differs at ${differs.join(", ")}: compare stills of those times sought from different places`);
    const length = info.frames / info.FPS;
    if (loop) await compare(`the loop closes: ${length.toFixed(3)}s equals 0s`, async () => (await shot(page, length)).equals(await shot(page, 0)));

    if (dist) {
      const [a, b] = [await open(args[0]), await open(dist)];
      if (a && b) {
        try {
          const apart = [];
          await compare(`${dist} matches the sources pixel for pixel`, async () => {
            for (const t of probes) if (!(await shot(b.page, t)).equals(await shot(a.page, t))) apart.push(t.toFixed(3) + "s");
            return !apart.length;
          });
          if (apart.length) console.log(`      differs at ${apart.join(", ")}`);
        } finally {
          await a.page.close();
          await b.page.close();
        }
      } else {
        await a?.page.close();
        await b?.page.close();
      }
    }
  } finally {
    await page.close();
  }
}
console.log(failed ? `${failed} check(s) failed` : "all checks passed");
process.exitCode = failed ? 1 : 0;
