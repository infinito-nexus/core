function hash(n, seed = 0) {
  let x = Math.imul((n | 0) ^ Math.imul(seed | 0, 0x9e3779b1), 0x85ebca6b);
  x ^= x >>> 13;
  x = Math.imul(x, 0xc2b2ae35);
  x ^= x >>> 16;
  return (x >>> 0) / 4294967296;
}

function noise(x, seed = 0) {
  const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
  return lerp(hash(i, seed), hash(i + 1, seed), u) * 2 - 1;
}

const frameOf = (t) => Math.round(t * FILM.FPS);
const stepOf = (t, rate) => Math.floor(t * rate + 1e-6);

function split(el, by = "char", masked = false) {
  const text = el.textContent;
  el.textContent = "";
  el.style.whiteSpace = "nowrap";
  const out = [];
  for (const part of by === "word" ? text.split(/(\s+)/) : [...text]) {
    if (!part) continue;
    if (/^\s+$/.test(part)) {
      el.append(part.replace(/ /g, " "));
      continue;
    }
    const s = document.createElement("span");
    s.className = "t";
    s.textContent = part;
    if (masked) {
      const m = document.createElement("span");
      m.className = "t mask";
      m.append(s);
      el.append(m);
    } else el.append(s);
    out.push(s);
  }
  return out;
}

const stagger = (t, t0, i, gap = 0.04, dur = 0.5, ease = E.out) => prog(t, t0 + i * gap, dur, ease);

function typewriter(text, t, t0, cps = 24) {
  return t < t0 ? "" : text.slice(0, Math.min(text.length, Math.floor((t - t0) * cps + 1e-6)));
}

const caret = (t, period = 1.06) => (t % period) < period / 2;

function scramble(text, t, t0, dur, seed = 1, glyphs = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&*") {
  if (t < t0) return "";
  const p = clamp((t - t0) / dur), k = stepOf(t, 20);
  return [...text].map((c, i) => (c === " " || i / text.length < p ? c : glyphs[Math.floor(hash(k * 131 + i, seed) * glyphs.length)])).join("");
}

function countUp(t, t0, dur, from, to, fmt = (v) => Math.round(v).toLocaleString("en-US"), ease = E.out) {
  return fmt(lerp(from, to, prog(t, t0, dur, ease)));
}

function drawPath(path, p) {
  if (!path.dataset.len) path.dataset.len = path.getTotalLength().toFixed(2);
  const len = Number(path.dataset.len);
  path.style.strokeDasharray = `${len} ${len}`;
  path.style.strokeDashoffset = (len * (1 - clamp(p))).toFixed(2);
}

function wipe(el, p, from = "left") {
  const r = ((1 - clamp(p)) * 100).toFixed(2) + "%";
  const sides = { left: `0 ${r} 0 0`, right: `0 0 0 ${r}`, top: `0 0 ${r} 0`, bottom: `${r} 0 0 0` };
  el.style.clipPath = `inset(${sides[from]})`;
}

function iris(el, p, x = "50%", y = "50%", radius = Math.hypot(FILM.W, FILM.H)) {
  el.style.clipPath = `circle(${(clamp(p) * radius).toFixed(2)}px at ${x} ${y})`;
}

function sweep(el, p, color = "rgba(255,255,255,.95)", width = 12) {
  if (!el.fxSweep) {
    const leaves = [...el.querySelectorAll("span.t:not(.mask)")];
    const parts = leaves.length ? leaves : [el];
    const k = document.getElementById("stage").getBoundingClientRect().width / FILM.W || 1, box = el.getBoundingClientRect();
    const w = box.width / k, ink = getComputedStyle(parts[0]).color;
    el.fxSweep = { w, parts: parts.map((leaf) => {
      Object.assign(leaf.style, { backgroundImage: `linear-gradient(100deg,${ink} ${50 - width}%,${color} 50%,${ink} ${50 + width}%)`, backgroundSize: `${(3 * w).toFixed(1)}px 100%`, backgroundRepeat: "no-repeat", webkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" });
      return { leaf, left: (leaf.getBoundingClientRect().left - box.left) / k };
    }) };
  }
  const { w, parts } = el.fxSweep, x = lerp(-1.8 * w, -0.2 * w, clamp(p));
  for (const { leaf, left } of parts) leaf.style.backgroundPosition = `${(x - left).toFixed(2)}px 0`;
}

function shake(t, t0, dur = 0.5, amp = 18, seed = 3) {
  if (t < t0 || t > t0 + dur) return { x: 0, y: 0, r: 0 };
  const d = 1 - prog(t, t0, dur, E.out), f = (t - t0) * 32;
  return { x: noise(f, seed) * amp * d, y: noise(f, seed + 1) * amp * d, r: noise(f, seed + 2) * amp * 0.06 * d };
}

function handheld(t, amp = 6, seed = 7) {
  return { x: noise(t * 0.9, seed) * amp, y: noise(t * 0.7, seed + 1) * amp, r: noise(t * 0.5, seed + 2) * amp * 0.04 };
}

const moveCamera = (el, { x = 0, y = 0, s = 1, r = 0 }) =>
  setT(el, `translate(${x.toFixed(2)}px,${y.toFixed(2)}px) rotate(${r.toFixed(3)}deg) scale(${s.toFixed(4)})`);

function kenBurns(el, t, t0, t1, from = { s: 1, x: 0, y: 0 }, to = { s: 1.12, x: 0, y: 0 }) {
  const p = clamp((t - t0) / (t1 - t0));
  moveCamera(el, { s: lerp(from.s, to.s, p), x: lerp(from.x, to.x, p), y: lerp(from.y, to.y, p) });
}

function glitch(el, t, t0, dur = 0.3, amount = 14, seed = 5) {
  if (t < t0 || t > t0 + dur) {
    el.style.filter = "";
    el.style.clipPath = "";
    setT(el, "none");
    return;
  }
  const k = stepOf(t, 30), dx = (hash(k, seed) * 2 - 1) * amount, band = hash(k, seed + 1) * 80;
  el.style.filter = `drop-shadow(${dx.toFixed(1)}px 0 0 rgba(255,0,72,.75)) drop-shadow(${(-dx).toFixed(1)}px 0 0 rgba(0,214,255,.75))`;
  el.style.clipPath = hash(k, seed + 2) > 0.5 ? `inset(${band.toFixed(1)}% 0 ${(100 - band - 12).toFixed(1)}% 0)` : "";
  setT(el, `translateX(${(dx * 0.5).toFixed(1)}px)`);
}

const grainLayer = (opacity = 0.12) =>
  `<div class="full" data-k="fxGrain" style="pointer-events:none;opacity:${opacity};mix-blend-mode:overlay;background-repeat:repeat"></div>`;

function grain(t, rate = 24, tiles = 8) {
  if (!grain.tiles) {
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    const ctx = c.getContext("2d"), img = ctx.createImageData(256, 256);
    grain.tiles = Array.from({ length: tiles }, (_, k) => {
      for (let i = 0; i < 65536; i++) {
        const v = Math.round(hash(i, k + 101) * 255);
        img.data.set([v, v, v, 255], i * 4);
      }
      ctx.putImageData(img, 0, 0);
      return `url(${c.toDataURL()})`;
    });
  }
  const k = stepOf(t, rate) % Math.max(1, Math.round(FILM.DURATION * rate));
  $.fxGrain.style.backgroundImage = grain.tiles[k % grain.tiles.length];
  $.fxGrain.style.backgroundPosition = `${Math.round(hash(k, 1) * 256)}px ${Math.round(hash(k, 2) * 256)}px`;
}

const vignetteLayer = (strength = 0.45) =>
  `<div class="full" style="pointer-events:none;background:radial-gradient(ellipse at 50% 50%,transparent 55%,rgba(0,0,0,${strength}) 100%)"></div>`;

const scanLayer = (opacity = 0.18) =>
  `<div class="full" data-k="fxScan" style="pointer-events:none;opacity:${opacity};background:repeating-linear-gradient(0deg,rgba(0,0,0,.6) 0 2px,transparent 2px 4px)"></div>`;

const scan = (t, speed = 40) => { $.fxScan.style.backgroundPosition = `0 ${(t * speed).toFixed(2)}px`; };

const leakLayer = (color = "255,150,80") =>
  `<div class="full" data-k="fxLeak" style="pointer-events:none;mix-blend-mode:screen;background:radial-gradient(circle at var(--lx) var(--ly),rgba(${color},.55),transparent 45%)"></div>`;

function leak(t, seed = 9) {
  $.fxLeak.style.setProperty("--lx", (50 + noise(t * 0.25, seed) * 45).toFixed(2) + "%");
  $.fxLeak.style.setProperty("--ly", (50 + noise(t * 0.2, seed + 1) * 40).toFixed(2) + "%");
}

function confetti(layer, t, t0, { n = 80, x = FILM.W / 2, y = FILM.H / 2, speed = 900, spread = 1.1, gravity = 1400, life = 2.2, colors = ["#F2C14E", "#F78154", "#4D9DE0", "#5FAD56", "#B370B0"], seed = 11 } = {}) {
  if (layer.children.length !== n) {
    layer.innerHTML = Array.from({ length: n }, (_, i) =>
      `<i class="abs" style="left:0;top:0;width:${8 + hash(i, seed) * 8}px;height:${5 + hash(i, seed + 1) * 6}px;margin:-5px 0 0 -6px;background:${colors[i % colors.length]};border-radius:2px"></i>`).join("");
  }
  const dt = t - t0, on = dt >= 0 && dt <= life;
  show(layer, on);
  if (!on) return;
  [...layer.children].forEach((el, i) => {
    const a = -Math.PI / 2 + (hash(i, seed + 2) - 0.5) * 2 * spread, v = speed * (0.45 + 0.75 * hash(i, seed + 3));
    const drag = 1 - Math.exp(-2.2 * dt), vx = Math.cos(a) * v, vy = Math.sin(a) * v;
    const px = x + (vx / 2.2) * drag, py = y + (vy / 2.2) * drag + 0.5 * gravity * 0.35 * dt * dt;
    const spin = (hash(i, seed + 4) - 0.5) * 1440 * dt, flip = Math.cos((hash(i, seed + 5) * 6 + 9) * dt);
    el.style.opacity = (1 - prog(t, t0 + life * 0.75, life * 0.25, E.linear)).toFixed(3);
    setT(el, `translate(${px.toFixed(1)}px,${py.toFixed(1)}px) rotate(${spin.toFixed(1)}deg) scaleY(${flip.toFixed(3)})`);
  });
}

const FX_JOIN = {
  cut() {},
  dissolve(a, b, p) { b.style.opacity = p.toFixed(3); },
  push(a, b, p, { dir = "left" } = {}) {
    const [dx, dy] = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] }[dir];
    setT(a, `translate(${(dx * p * FILM.W).toFixed(1)}px,${(dy * p * FILM.H).toFixed(1)}px)`);
    setT(b, `translate(${(dx * (p - 1) * FILM.W).toFixed(1)}px,${(dy * (p - 1) * FILM.H).toFixed(1)}px)`);
  },
  cover(a, b, p, { dir = "left" } = {}) {
    const [dx, dy] = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] }[dir];
    setT(b, `translate(${(dx * (p - 1) * FILM.W).toFixed(1)}px,${(dy * (p - 1) * FILM.H).toFixed(1)}px)`);
    a.style.filter = `brightness(${(1 - 0.25 * p).toFixed(3)})`;
  },
  zoom(a, b, p) {
    setT(a, `scale(${(1 + 0.6 * p).toFixed(4)})`);
    a.style.opacity = (1 - p).toFixed(3);
    setT(b, `scale(${(0.8 + 0.2 * p).toFixed(4)})`);
    b.style.opacity = p.toFixed(3);
  },
  whip(a, b, p, { dir = "left" } = {}) {
    const s = dir === "left" ? -1 : 1, blur = (Math.sin(Math.PI * p) * 28).toFixed(1);
    setT(a, `translateX(${(s * p * FILM.W).toFixed(1)}px)`);
    setT(b, `translateX(${(s * (p - 1) * FILM.W).toFixed(1)}px)`);
    a.style.filter = b.style.filter = `blur(${blur}px)`;
  },
  wipe(a, b, p, { from = "left" } = {}) { wipe(b, p, from); },
  iris(a, b, p, { x, y } = {}) { iris(b, p, x, y); },
};

function sequence(t, shots) {
  shots.forEach((s, i) => {
    const next = shots[i + 1], join = next && next.join ? next.join : ["cut", 0];
    const on = t >= s.t0 && t < (next ? next.t0 + (join[1] || 0) : Infinity);
    const el = $[s.k];
    show(el, on);
    el.style.transform = el.style.opacity = el.style.filter = el.style.clipPath = "";
  });
  shots.forEach((s, i) => {
    if (!i || !s.join) return;
    const [kind, dur = 0.6, o = {}] = s.join;
    if (t >= s.t0 && t < s.t0 + dur) FX_JOIN[kind]($[shots[i - 1].k], $[s.k], prog(t, s.t0, dur, o.ease || E.inOut), o);
  });
}
