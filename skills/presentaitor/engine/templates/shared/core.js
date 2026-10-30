const FILM = {};
const HOLDS = [];

function film({ W = 1440, H = 1440, FPS = 60, BPM = 120, BEATS, holds = [] }) {
  const timed = BEATS === undefined;
  if (timed && !window.TIMING) throw new Error("film() without BEATS is timed by the voice: run voiceover.py to write timing.js");
  Object.assign(FILM, { W, H, FPS, BPM: timed ? window.TIMING.bpm : BPM, P: 60 / (timed ? window.TIMING.bpm : BPM) });
  FILM.frames = timed ? Math.round(window.TIMING.duration * FPS) : Math.round(BEATS * FILM.P * FPS);
  FILM.DURATION = FILM.frames / FPS;
  FILM.BEATS = timed ? FILM.DURATION / FILM.P : BEATS;
  HOLDS.splice(0, HOLDS.length, ...holds);
}
const B = (b) => (b + HOLDS.reduce((s, [at, len]) => s + (b >= at ? len : 0), 0) - 1) * FILM.P;

function line(id) {
  const l = window.TIMING && window.TIMING.lines[id];
  if (!l) throw new Error(`no line ${id} in timing.js: add it to voiceover.json and run voiceover.py`);
  return l;
}

function scene(id) {
  const s = window.TIMING && window.TIMING.scenes.find((x) => x.id === id);
  if (!s) throw new Error(`no scene ${id} in timing.js: add it to voiceover.json and run voiceover.py`);
  return s;
}

const clamp = (v, a = 0, b = 1) => (v < a ? a : v > b ? b : v);
const lerp = (a, b, p) => a + (b - a) * p;

function cubicBezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (t) => ((ax * t + bx) * t + cx) * t;
  const sy = (t) => ((ay * t + by) * t + cy) * t;
  const dx = (t) => (3 * ax * t + 2 * bx) * t + cx;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 8; i++) {
      const e = sx(t) - x, d = dx(t);
      if (Math.abs(e) < 1e-7 || Math.abs(d) < 1e-7) break;
      t -= e / d;
    }
    let lo = 0, hi = 1;
    for (let i = 0; i < 24 && Math.abs(sx(t) - x) > 1e-6; i++) {
      if (sx(t) < x) lo = t; else hi = t;
      t = (lo + hi) / 2;
    }
    return sy(t);
  };
}

const E = {
  linear: (x) => x,
  inOut: cubicBezier(0.65, 0, 0.35, 1),
  smooth: cubicBezier(0.45, 0, 0.2, 1),
  out: cubicBezier(0.16, 1, 0.3, 1),
  in: cubicBezier(0.55, 0, 0.85, 0.35),
  snappy: cubicBezier(0.2, 0.9, 0.3, 1),
};

const prog = (t, t0, dur, ease = E.inOut) => ease(clamp((t - t0) / dur));

function spring(t, t0, response = 0.32, damping = 0.86) {
  if (t <= t0) return 0;
  const dt = t - t0;
  const w0 = (2 * Math.PI) / response;
  if (damping < 1) {
    const wd = w0 * Math.sqrt(1 - damping * damping);
    const e = Math.exp(-damping * w0 * dt);
    return 1 - e * (Math.cos(wd * dt) + ((damping * w0) / wd) * Math.sin(wd * dt));
  }
  return 1 - Math.exp(-w0 * dt) * (1 + w0 * dt);
}

function track(t, base, keys) {
  let v = base, prevTo = base;
  for (const k of keys) {
    const f = k.spring ? spring(t, k.t, k.spring[0], k.spring[1]) : prog(t, k.t, k.d, k.e || E.inOut);
    v += (k.to - prevTo) * f;
    prevTo = k.to;
  }
  return v;
}

const loop = (t, cycles = 1, phase = 0) => Math.sin(2 * Math.PI * (cycles * t / FILM.DURATION + phase)) - Math.sin(2 * Math.PI * phase);

function press(t, t0, depth = 0.94) {
  if (t < t0) return 1;
  return 1 - (1 - depth) * (prog(t, t0, 0.07, E.out) - spring(t, t0 + 0.1, 0.3, 0.7));
}

function pulse(t, t0, dur = 0.35) {
  if (t < t0 || t > t0 + dur) return 0;
  return Math.sin((Math.PI * (t - t0)) / dur);
}

const $ = {};
function collect(root) {
  root.querySelectorAll("[data-k]").forEach((el) => { $[el.dataset.k] = el; });
}

const show = (el, on) => { el.style.visibility = on ? "" : "hidden"; };
const setT = (el, v) => { el.style.transform = v; };
const MASK_PAD_EM = 0.4;
const TRAVEL = (p) => `translateY(calc(${(p * 100).toFixed(2)}% + ${(p * 2 * MASK_PAD_EM).toFixed(3)}em))`;
const rise = (el, p) => setT(el, TRAVEL(1 - p));
const sink = (el, p) => setT(el, TRAVEL(-p));
const T = (x, y, s = 1) => `translate(${x.toFixed(2)}px,${y.toFixed(2)}px) scale(${s.toFixed(4)})`;
const mixRect = (a, b, p) => ({ x: lerp(a.x, b.x, p), y: lerp(a.y, b.y, p), w: lerp(a.w, b.w, p), h: lerp(a.h, b.h, p), r: lerp(a.r, b.r, p) });

function rectCss(el, r) {
  el.style.left = r.x.toFixed(2) + "px";
  el.style.top = r.y.toFixed(2) + "px";
  el.style.width = r.w.toFixed(2) + "px";
  el.style.height = r.h.toFixed(2) + "px";
  el.style.borderRadius = r.r.toFixed(2) + "px";
}

function measure(text, size, weight, css = "") {
  const stage = document.getElementById("stage");
  const el = document.createElement("span");
  el.className = "t";
  el.style.cssText = `position:absolute;left:0;top:0;visibility:hidden;font-size:${size}px;font-weight:${weight};${css}`;
  el.textContent = text;
  stage.appendChild(el);
  const w = el.getBoundingClientRect().width / (stage.getBoundingClientRect().width / FILM.W || 1);
  el.remove();
  return w;
}

function sym(key, size, color, css = "") {
  const s = ASSETS.sym[key];
  if (!s) throw new Error(`no symbol ${key} in assets.js: render it with symbols.swift, pack it with assets.py --sym`);
  const mask = `url(${s.src}) 0 0 / 100% 100% no-repeat`;
  return `<i style="display:block;flex:none;width:${(s.w * size).toFixed(2)}px;height:${(s.h * size).toFixed(2)}px;background:${color};-webkit-mask:${mask};mask:${mask};${css}"></i>`;
}

function roller(host, css) {
  host.innerHTML = `<span class="t" style="position:absolute;left:0;top:0;${css}"></span><span class="t" style="position:absolute;left:0;top:0;${css}"></span>`;
  return { a: host.children[0], b: host.children[1], last: [null, null] };
}

function roll(r, t, steps, dur = 0.34) {
  let i = -1;
  for (let k = 0; k < steps.length; k++) if (t >= steps[k].t) i = k;
  const put = (el, slot, v) => { if (r.last[slot] !== v) { el.textContent = v; r.last[slot] = v; } };
  if (i < 0) { show(r.a, false); show(r.b, false); return; }
  const cur = steps[i], prev = steps[i - 1];
  const p = prog(t, cur.t, dur, E.snappy);
  if (!prev || p >= 1) {
    put(r.a, 0, cur.v); show(r.a, true); show(r.b, false);
    setT(r.a, prev ? "none" : TRAVEL(1 - prog(t, cur.t, dur, E.out)));
    return;
  }
  put(r.a, 0, prev.v); put(r.b, 1, cur.v);
  show(r.a, true); show(r.b, true);
  setT(r.a, TRAVEL(-p));
  setT(r.b, TRAVEL(1 - p));
}
