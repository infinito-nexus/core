import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { basename, join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { pathToFileURL } from "node:url";

export function installedBrowser() {
  const root = join(process.env.MOTION_DESIGNER_HOME || join(homedir(), ".cache", "motion-designer"), "browsers", "chrome-headless-shell");
  if (!existsSync(root)) return null;
  for (const build of readdirSync(root).sort().reverse()) {
    for (const dir of readdirSync(join(root, build))) {
      for (const name of ["chrome-headless-shell", "chrome-headless-shell.exe"]) {
        const bin = join(root, build, dir, name);
        if (existsSync(bin)) return bin;
      }
    }
  }
  return null;
}

export const CHROME = [
  process.env.CHROME,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  installedBrowser(),
].find((p) => p && existsSync(p));

export async function openPage(url, { width = 1440, height = 1440, scale = 1 } = {}) {
  if (!CHROME) throw new Error("Chrome not found: run scripts/doctor.sh, or set CHROME to a Chrome or Chromium binary");
  const profile = mkdtempSync(join(tmpdir(), "motion-designer-"));
  const headless = basename(CHROME).startsWith("chrome-headless-shell") ? [] : ["--headless=new"];
  const chrome = spawn(CHROME, [
    ...headless, "--disable-gpu", "--hide-scrollbars", "--mute-audio",
    "--run-all-compositor-stages-before-draw", "--disable-low-res-tiling", "--disable-partial-raster",
    "--allow-file-access-from-files", `--force-device-scale-factor=${scale}`,
    `--window-size=${width},${height}`, "--remote-debugging-port=0",
    `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe"] });
  const quit = async () => {
    if (chrome.exitCode === null && chrome.signalCode === null) {
      const gone = new Promise((r) => chrome.once("exit", r));
      chrome.kill("SIGTERM");
      const stuck = setTimeout(() => chrome.kill("SIGKILL"), 5000);
      await gone;
      clearTimeout(stuck);
    }
    for (let attempt = 1; attempt <= 6; attempt++) {
      try {
        rmSync(profile, { recursive: true, force: true });
        break;
      } catch (e) {
        if (attempt < 6) await sleep(attempt * 100);
        else console.warn(`could not remove Chrome's profile ${profile}: ${e.code || e.message}`);
      }
    }
  };
  try {
    return await connect(chrome, url, { scale, width, height }, quit);
  } catch (e) {
    await quit();
    throw e;
  }
}

async function connect(chrome, url, { scale, width, height }, quit) {
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = "";
    chrome.stderr.on("data", (d) => {
      buf += d;
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) resolve(m[1]);
    });
    chrome.on("exit", () => reject(new Error("chrome exited before it was ready")));
  });
  const port = new URL(wsUrl).port;
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));

  let id = 0;
  const pending = new Map();
  const listeners = new Map();
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    } else if (msg.method && listeners.has(msg.method)) {
      for (const fn of listeners.get(msg.method)) fn(msg.params);
    }
  });
  const limit = Number(process.env.MOTION_DESIGNER_CDP_TIMEOUT || 90) * 1000;
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const mid = ++id;
    const timer = setTimeout(() => {
      pending.delete(mid);
      reject(new Error(`Chrome did not answer ${method} within ${limit / 1000} s`));
    }, limit);
    pending.set(mid, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const on = (method, fn) => {
    if (!listeners.has(method)) listeners.set(method, []);
    listeners.get(method).push(fn);
  };

  const errors = [];
  on("Runtime.exceptionThrown", (p) => errors.push(p.exceptionDetails?.exception?.description || p.exceptionDetails?.text));
  on("Runtime.consoleAPICalled", (p) => {
    if (p.type === "error") errors.push(p.args.map((a) => a.value ?? a.description).join(" "));
  });
  await send("Runtime.enable");
  await send("Page.enable");
  const resize = (w, h) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: scale, mobile: false });
  await resize(width, height);
  const loaded = new Promise((r) => on("Page.loadEventFired", r));
  await send("Page.navigate", { url });
  await loaded;

  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const screenshot = async () => {
    const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false, optimizeForSpeed: false });
    return Buffer.from(r.data, "base64");
  };
  const close = async () => {
    try { ws.close(); } catch {}
    await quit();
  };
  return { send, evaluate, screenshot, resize, close, errors };
}

export async function openFilm(pagePath, { scale = 1, preview = false } = {}) {
  const url = `${pathToFileURL(pagePath).href}?render${preview ? "&preview" : ""}`;
  const page = await openPage(url, { scale });
  try {
    const info = await page.evaluate("seek(0).then(() => window.FILM_INFO)");
    if (!info || !info.frames) throw new Error(`${pagePath} does not expose FILM_INFO with frames`);
    if (info.W !== 1440 || info.H !== 1440) {
      await page.resize(info.W, info.H);
      await page.evaluate("seek(0)");
    }
    return { page, info };
  } catch (e) {
    await page.close();
    throw e;
  }
}
