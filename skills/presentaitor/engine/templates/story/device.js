const KIT = {};

function headline(key, text, { size = 88, weight = 700, lh = 1.14, color = "var(--ink)", accent = "var(--accent)" } = {}) {
  const k = (KIT[key] = { words: 0, letters: 0, size, strokes: [] });
  const lines = text.split("\n").map((line) => {
    const [plain = "", acc = "", tail = ""] = line.split("*");
    const words = plain.split(" ").filter(Boolean).map((w) => `<span class="mask hl-w"><span data-k="${key}w${k.words++}" class="t" style="font-weight:${weight};color:${color}">${w}</span></span>`);
    let accentHtml = "";
    if (acc) {
      const letters = [...acc].map((ch) => `<span data-k="${key}a${k.letters++}" style="visibility:hidden">${ch === " " ? "&nbsp;" : ch}</span>`).join("");
      const width = measure(acc, size, 400, "font-family:var(--serif);font-style:italic");
      k.strokes.push(width);
      accentHtml = `<span class="hl-acc" style="font-family:var(--serif);font-style:italic;font-weight:400;color:${accent}">${letters}
        <svg class="abs" style="left:0;top:${(size * 0.98).toFixed(1)}px;overflow:visible" width="${width.toFixed(1)}" height="${(size * 0.14).toFixed(1)}">
          <path data-k="${key}u${k.strokes.length - 1}" d="M2 ${(size * 0.09).toFixed(1)} Q${(width * 0.45).toFixed(1)} ${(size * 0.02).toFixed(1)} ${(width - 2).toFixed(1)} ${(size * 0.07).toFixed(1)}" fill="none" stroke="${accent}" stroke-width="${(size * 0.035).toFixed(2)}" stroke-linecap="round"/></svg></span>`;
    }
    const tailWords = tail.split(" ").filter(Boolean).map((w) => `<span class="mask hl-w"><span data-k="${key}w${k.words++}" class="t" style="font-weight:${weight};color:${color}">${w}</span></span>`);
    return `<div class="hl-line" style="height:${(size * lh).toFixed(1)}px">${words.join("")}${accentHtml}${tailWords.join("")}</div>`;
  });
  return `<div class="hl" data-k="${key}" style="font-size:${size}px">${lines.join("")}</div>`;
}

function headlineAt(key, t, t0, out = Infinity) {
  const k = KIT[key];
  const leave = prog(t, out, 0.35, E.in);
  for (let i = 0; i < k.words; i++) {
    const p = clamp(spring(t, t0 + i * 0.07, 0.42, 0.9), 0, 1.05);
    setT($[key + "w" + i], TRAVEL((1 - p) + leave));
  }
  const { typed, done } = headlineTimes(key, t0);
  for (let j = 0; j < k.letters; j++) show($[key + "a" + j], t >= typed + j * 0.035 && leave < 0.5);
  for (let l = 0; l < k.strokes.length; l++) {
    const path = $[key + "u" + l], len = k.strokes[l] * 1.05 + 4;
    path.style.strokeDasharray = `${len.toFixed(1)} ${len.toFixed(1)}`;
    path.style.strokeDashoffset = (len * (1 - prog(t, done, 0.35, E.out) + leave)).toFixed(2);
  }
  return done;
}

function headlineTimes(key, t0) {
  const k = KIT[key], typed = t0 + k.words * 0.07 + 0.08;
  return { typed, done: typed + k.letters * 0.035, letters: [...Array(k.letters).keys()].map((j) => typed + j * 0.035) };
}

const headlineCues = (key, t0) => {
  const h = headlineTimes(key, t0);
  return [["tick", t0, { gain: -3 }], ...h.letters.map((t) => ["tick", t, { gain: -2 }]), ...(KIT[key].strokes.length ? [["swish", h.done]] : [])];
};

const scene = (key, color, inner = "") => `<div class="full" data-k="${key}" style="background:${color}">${inner}</div>`;
const panel = (key, r, bg, inner = "") => `<div class="abs" data-k="${key}" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;border-radius:${r.r ?? 36}px;background:${bg};overflow:hidden">${inner}</div>`;

function sceneAt(key, t, tIn, tGone = Infinity) {
  const el = $[key];
  const on = t >= tIn && t < tGone;
  show(el, on);
  if (!on) return 0;
  const p = prog(t, tIn, 0.55, E.inOut);
  el.style.clipPath = p < 1 ? `inset(0 0 0 ${((1 - p) * 100).toFixed(3)}%)` : "none";
  return p;
}

const driftAt = (el, t, tIn, dist = 90) => setT(el, `translateX(${((1 - clamp(spring(t, tIn + 0.08, 0.6, 0.9), 0, 1.02)) * dist).toFixed(2)}px)`);

const card = (key, r, inner) => `<div class="abs kit-card" data-k="${key}" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px">${inner}</div>`;

function cardAt(key, t, t0) {
  const p = clamp(spring(t, t0, 0.5, 0.82), 0, 1.1);
  show($[key], t >= t0);
  $[key].style.opacity = Math.min(1, p * 1.6).toFixed(3);
  setT($[key], `translateY(${((1 - p) * 26).toFixed(2)}px) scale(${(0.97 + 0.03 * p).toFixed(4)})`);
}

const check = (key) => `<span class="abs kit-check" data-k="${key}"><svg viewBox="0 0 24 24" width="24" height="24"><path data-k="${key}m" d="M6 12.5l4 4 8-9" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="20 20"/></svg></span>`;

function checkAt(key, t, t0) {
  const p = clamp(spring(t, t0, 0.35, 0.7), 0, 1.15);
  $[key].style.background = t >= t0 ? "var(--accent)" : "transparent";
  $[key].style.borderColor = t >= t0 ? "var(--accent)" : "var(--hair2)";
  setT($[key], `scale(${(1 + 0.18 * pulse(t, t0, 0.3)).toFixed(4)})`);
  $[key + "m"].style.strokeDashoffset = (20 * (1 - clamp(p))).toFixed(2);
}

const toggle = (key) => `<span class="abs kit-toggle" data-k="${key}"><span class="abs" data-k="${key}k"></span></span>`;

function toggleAt(key, t, t0) {
  const p = clamp(spring(t, t0, 0.38, 0.72), 0, 1.08);
  $[key].style.background = `color-mix(in srgb, var(--accent) ${(clamp(p) * 100).toFixed(1)}%, var(--hair2))`;
  setT($[key + "k"], `translateX(${(p * 26).toFixed(2)}px)`);
}

const bars = (key, labels) => labels.map((l, i) => `<div class="abs kit-bar-label" style="left:${i * 92}px;bottom:0;width:60px">${l}</div>
  <div class="abs kit-bar" style="left:${i * 92 + 10}px;bottom:42px;width:40px;height:300px"><div class="abs" data-k="${key}${i}" style="left:0;bottom:0;width:40px;border-radius:12px;background:var(--accent)"></div></div>`).join("");

function barsAt(key, values, t, t0, step = 0.12) {
  values.forEach((v, i) => {
    const p = clamp(spring(t, t0 + i * step, 0.45, 0.78), 0, 1.08);
    $[key + i].style.height = (300 * v * p).toFixed(2) + "px";
  });
}

const ring = (key, size) => `<svg class="abs" style="left:0;top:0" width="${size}" height="${size}" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="44" fill="none" stroke="var(--hair2)" stroke-width="7"/>
  <circle data-k="${key}" cx="50" cy="50" r="44" fill="none" stroke="var(--accent)" stroke-width="7" stroke-linecap="round" transform="rotate(-90 50 50)" stroke-dasharray="276.46 276.46"/></svg>`;
const ringAt = (key, p) => { $[key].style.strokeDashoffset = (276.46 * (1 - clamp(p))).toFixed(2); };

const character = (key, inner, w, h) => `<div class="abs" data-k="${key}" style="left:0;top:0;width:${w}px;height:${h}px;transform-origin:50% 100%">${inner}</div>`;

function characterAt(key, t, { x, y, s = 1, lean = 0, hop = 0, squash = 0 }) {
  const el = $[key], w = parseFloat(el.style.width), h = parseFloat(el.style.height);
  const sq = squash + 0.02 * loop(t, Math.max(1, Math.round(FILM.DURATION / 2.4)));
  setT(el, `translate(${(x - w / 2).toFixed(2)}px,${(y - h - hop).toFixed(2)}px) rotate(${lean.toFixed(3)}rad) scale(${(s * (1 - 0.5 * sq)).toFixed(4)},${(s * (1 + sq)).toFixed(4)})`);
}
