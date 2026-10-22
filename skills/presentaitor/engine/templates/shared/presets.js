const PRESETS = {};

function preset(name, spec) {
  PRESETS[name] = spec;
}

const opts = (name, o = {}) => ({ ...window.PRESET_DEFAULTS[name], ...o });

function tune(name, o) {
  Object.assign(window.PRESET_DEFAULTS[name], o);
}

const span = (ref) => (typeof ref === "string" ? { t0: line(ref).start, t1: line(ref).end } : ref);

function reveal(words, t, t0, o) {
  const P = opts("reveal", o);
  words.forEach((w, i) => rise(w, prog(t, t0 + i * P.stagger, P.dur, E.out)));
}

const ZOOMS = { subtle: 0.5, normal: 1, punch: 1.5 };

function focusTarget(rect, zoom, P) {
  const auto = Math.max(1, Math.min(P.maxZoom, (FILM.W * P.fill) / rect.w, (FILM.H * P.fill) / rect.h));
  const k = typeof zoom === "number" ? zoom : 1 + (auto - 1) * ZOOMS[zoom || "normal"];
  return { x: rect.x + rect.w / 2, y: rect.y + rect.h / 2, s: 1 + (k - 1) * P.intensity };
}

function focus(t, shots, o) {
  const P = opts("focus", o), wide = { x: FILM.W / 2, y: FILM.H / 2, s: 1 };
  const keys = [];
  shots.forEach((sh, i) => {
    const { t0, t1 } = span(sh.line || sh);
    keys.push({ t: t0, to: focusTarget(sh.rect, sh.zoom, P) });
    const next = shots[i + 1];
    if (!next || span(next.line || next).t0 - t1 > P.wideAfter) keys.push({ t: t1, to: wide });
  });
  let cam = { ...wide }, from = { ...wide };
  for (const k of keys) {
    const p = spring(t, k.t, P.ease * 1.6, P.damping);
    cam = { x: cam.x + (k.to.x - from.x) * p, y: cam.y + (k.to.y - from.y) * p, s: cam.s + (k.to.s - from.s) * p };
    from = k.to;
  }
  return cam;
}

function applyFocus(el, cam) {
  const tx = clamp(FILM.W / 2 - cam.x * cam.s, FILM.W - FILM.W * cam.s, 0);
  const ty = clamp(FILM.H / 2 - cam.y * cam.s, FILM.H - FILM.H * cam.s, 0);
  el.style.transformOrigin = "0 0";
  setT(el, `translate(${tx.toFixed(2)}px,${ty.toFixed(2)}px) scale(${cam.s.toFixed(4)})`);
}

const cursorLayer = (k = "cur") =>
  `<div data-k="${k}Rip" class="abs" style="left:0;top:0;pointer-events:none;z-index:49"></div>` +
  `<svg data-k="${k}" class="abs" viewBox="0 0 24 24" style="left:0;top:0;transform-origin:4px 4px;z-index:50;pointer-events:none;overflow:visible">` +
  `<path d="M3 2l17 9-7.5 1.8L9 20z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;

function cursorAt(t, path, P) {
  let i = 0;
  while (i < path.length - 1 && t >= path[i + 1].t) i++;
  const a = path[i], b = path[Math.min(i + 1, path.length - 1)];
  if (a === b) return { x: a.x, y: a.y };
  const move = Math.min(0.75, (b.t - a.t) * 0.8), raw = clamp((t - (b.t - move)) / move);
  const p = E.inOut(raw) + P.overshoot * Math.sin(Math.PI * raw) * (raw > 0.6 ? (raw - 0.6) / 0.4 : 0);
  const dx = b.x - a.x, dy = b.y - a.y, dist = Math.hypot(dx, dy) || 1, bend = Math.sin(Math.PI * clamp(p)) * dist * P.arc;
  return { x: a.x + dx * p - (dy / dist) * bend, y: a.y + dy * p + (dx / dist) * bend };
}

function cursor(t, path, o, k = "cur") {
  const P = opts("cursor", o), clicks = path.filter((c) => c.click), host = $[k + "Rip"];
  if (host.children.length !== clicks.length) {
    host.innerHTML = clicks.map(() => `<i class="abs" style="border-radius:50%;border:3px solid var(--accent2,#6aa8ff)"></i>`).join("");
  }
  let press = 1;
  clicks.forEach((c, i) => {
    const dt = t - c.t, r = host.children[i], p = clamp(dt / P.rippleTime), on = dt >= 0 && dt < P.rippleTime;
    if (dt >= 0 && dt < P.dipTime) press = Math.min(press, 1 - (1 - P.dip) * Math.sin((Math.PI * dt) / P.dipTime));
    show(r, on);
    if (on) {
      const rad = P.ripple * E.out(p);
      Object.assign(r.style, { left: c.x - rad + "px", top: c.y - rad + "px", width: rad * 2 + "px", height: rad * 2 + "px", opacity: (1 - p).toFixed(3) });
    }
  });
  const at = cursorAt(t, path, P), el = $[k];
  el.style.width = el.style.height = P.size + "px";
  setT(el, `translate(${(at.x - 4).toFixed(2)}px,${(at.y - 4).toFixed(2)}px) scale(${press.toFixed(3)})`);
  return { ...at, press };
}

const captionLayer = (k = "cap", css = "") =>
  `<div data-k="${k}" class="abs" style="left:0;width:100%;bottom:90px;text-align:center;font:800 64px/1.15 var(--sans,Inter),sans-serif;color:#fff;z-index:60;${css}"></div>`;

const captionsOn = () => Boolean(window.TIMING && window.TIMING.captions);

function lineWords(ids) {
  return ids.flatMap((id) => {
    const words = window.TIMING && window.TIMING.words && window.TIMING.words[id];
    if (!words) throw new Error(`no word timings for ${id} in timing.js: run voiceover.py`);
    return words.map((w) => ({ ...w, line: id }));
  });
}

function captions(t, words, o, k = "cap") {
  const P = opts("captions", o), box = $[k];
  if (o?.on === false || (o?.on === undefined && !captionsOn())) return show(box, false);
  const pages = [];
  for (const w of words) {
    const last = pages[pages.length - 1];
    if (last && last.length < P.perPage && last[0].line === w.line) last.push(w);
    else pages.push([w]);
  }
  const page = pages.find((p) => t >= p[0].t0 - 0.05 && t < p[p.length - 1].t1 + 0.25);
  show(box, Boolean(page));
  if (!page) return null;
  const key = page[0].t0;
  if (box.dataset.page !== String(key)) {
    box.innerHTML = page.map((w) => `<span style="display:inline-block;margin:0 .14em">${w.w}</span>`).join("");
    box.dataset.page = String(key);
  }
  const pin = prog(t, page[0].t0 - 0.05, 0.25, E.out);
  box.style.opacity = pin.toFixed(3);
  setT(box, `translateY(${((1 - pin) * 24).toFixed(2)}px)`);
  [...box.children].forEach((el, i) => {
    const w = page[i], p = spring(t, w.t0 - 0.06, P.response, P.damping);
    el.style.opacity = clamp(p * 2).toFixed(3);
    setT(el, `translateY(${((1 - p) * P.rise).toFixed(2)}px) scale(${lerp(P.fromScale, 1, p).toFixed(4)})`);
    el.style.color = t >= w.t0 && t < w.t1 ? P.active : "";
  });
  return page.map((w) => w.w).join(" ");
}

const spotlightLayer = (k = "spot", tint = "#05070c") =>
  `<svg data-k="${k}" class="full" viewBox="0 0 ${FILM.W} ${FILM.H}" style="pointer-events:none;z-index:40">` +
  `<defs><mask id="${k}M"><rect width="${FILM.W}" height="${FILM.H}" fill="#fff"/><rect data-k="${k}Hole" fill="#000" filter="url(#${k}F)"/></mask>` +
  `<filter id="${k}F" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur data-k="${k}Blur" stdDeviation="0"/></filter></defs>` +
  `<rect data-k="${k}Shade" width="${FILM.W}" height="${FILM.H}" fill="${tint}" mask="url(#${k}M)"/></svg>`;

function spotlight(t, seq, on, o, k = "spot") {
  const P = opts("spotlight", o);
  const vis = prog(t, on[0], 0.5, E.inOut) * (1 - prog(t, on[1], 0.5, E.inOut));
  let r = { ...seq[0].rect };
  for (let i = 1; i < seq.length; i++) r = mixRect({ r: 0, ...r }, { r: 0, ...seq[i].rect }, spring(t, seq[i].t, P.response, P.damping));
  const hole = $[k + "Hole"];
  Object.entries({ x: r.x - P.padding, y: r.y - P.padding, width: r.w + 2 * P.padding, height: r.h + 2 * P.padding, rx: P.radius })
    .forEach(([a, v]) => hole.setAttribute(a, v.toFixed(1)));
  $[k + "Blur"].setAttribute("stdDeviation", (P.feather / 2).toFixed(2));
  $[k + "Shade"].setAttribute("opacity", (P.dim * vis).toFixed(3));
  return r;
}

const emphasizeLayer = (k = "emp") =>
  `<svg data-k="${k}" class="full" viewBox="0 0 ${FILM.W} ${FILM.H}" style="pointer-events:none;z-index:45;overflow:visible"></svg>` +
  `<div data-k="${k}Label" class="abs" style="background:var(--callout-bg,#1b1f29);color:var(--callout-ink,#fff);padding:10px 16px;border-radius:10px;font:600 22px var(--sans,system-ui),sans-serif;white-space:nowrap;transform-origin:0 50%;z-index:46"></div>`;

function emphasize(t, ref, rect, label, o, k = "emp") {
  const P = opts("emphasize", o), { t0, t1 } = span(ref), svg = $[k], lab = $[k + "Label"];
  const s = t0 + P.lead, a = spring(t, s, P.response, P.damping), out = 1 - prog(t, t1, P.fadeOut, E.inOut);
  const on = t >= s && t <= t1 + P.fadeOut;
  show(svg, on);
  show(lab, on);
  if (!on) return 0;
  const x0 = rect.x + rect.w + 6, x = rect.x + rect.w + 40, y = rect.y + rect.h / 2, ink = "var(--callout-bg,#1b1f29)";
  svg.innerHTML = `<path d="M${x0} ${y} L${lerp(x0, x, a).toFixed(1)} ${y}" stroke="${ink}" stroke-width="${P.stroke / 2}" opacity="${out.toFixed(3)}"/>` +
    `<circle cx="${x0}" cy="${y}" r="${P.stroke}" fill="${ink}" opacity="${(out * clamp(a * 3)).toFixed(3)}"/>`;
  if (lab.textContent !== label) lab.textContent = label;
  Object.assign(lab.style, { left: x + "px", top: y - 24 + "px", opacity: (clamp(a) * out).toFixed(3) });
  setT(lab, `scale(${lerp(0.8, 1, a).toFixed(4)})`);
  return a * out;
}

function morph(t, el, from, to, open, close = Infinity, o = {}) {
  const P = opts("morph", o), f = (t0) => spring(t, t0, P.response, P.damping);
  const p = f(open) - f(close);
  rectCss(el, mixRect(from, to, p));
  if (o.source) o.source.style.opacity = t >= open && p > 0.001 ? "0" : "";
  if (o.content) o.content.style.opacity = (prog(t, open + P.contentDelay, P.contentFade, E.out) * (1 - prog(t, close - 0.1, 0.2, E.out))).toFixed(3);
  return p;
}

FX_JOIN.whipPush = (a, b, p, { blur = window.PRESET_DEFAULTS.whip.blur } = {}) => {
  const blurPx = (Math.sin(Math.PI * p) * blur).toFixed(1);
  setT(a, `translateX(${(-p * FILM.W).toFixed(1)}px)`);
  setT(b, `translateX(${((1 - p) * FILM.W).toFixed(1)}px)`);
  a.style.filter = b.style.filter = `blur(${blurPx}px)`;
};

function transition(kind, o) {
  if (kind === "whip") {
    const P = opts("whip", o);
    return ["whipPush", P.beats * FILM.P, { ease: E.inOut, blur: P.blur }];
  }
  if (kind === "morph") return opts("morph", o);
  throw new Error(`no transition ${kind}: use whip or morph`);
}

function beatCuts(keys, startBeat = 1, o) {
  const P = opts("whip", o);
  return keys.map((k, i) => ({ k, t0: B(startBeat + i * P.every), ...(i ? { join: transition("whip", o) } : {}) }));
}

function parallax(layers, t, t0, t1, o) {
  const P = opts("parallax", o), cx = lerp(P.travel, -P.travel, prog(t, t0, t1 - t0, E.inOut));
  layers.forEach((el, i) => setT(el, `translate(${(cx * P.factors[Math.min(i, P.factors.length - 1)]).toFixed(2)}px,0px)`));
  return cx;
}

function tilt(t, t0, els, o) {
  const P = opts("tilt", o), p = spring(t, t0, P.response, P.damping);
  const rx = lerp(P.angle * P.fromX, P.angle * P.toX, p), ry = lerp(P.angle * P.fromY, P.angle * P.toY, p), ty = lerp(P.rise, 0, p);
  if (els.wrap) els.wrap.style.perspective = P.perspective + "px";
  setT(els.screen, `translateY(${ty.toFixed(1)}px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)`);
  if (els.gloss) els.gloss.style.background = `radial-gradient(circle at ${(50 + ry * 2.2).toFixed(1)}% ${(30 - rx * 2).toFixed(1)}%, rgba(255,255,255,${P.gloss}), transparent 55%)`;
  if (els.shadow) {
    els.shadow.style.opacity = lerp(0.9, 0.4, Math.abs(rx) / 40).toFixed(3);
    setT(els.shadow, `translateY(${(ty * 0.6).toFixed(1)}px) scaleX(${(1 - Math.abs(ry) / 120).toFixed(3)})`);
  }
  return { rx, ry, ty };
}

function chart(svg, t, t0, data, o = {}) {
  const P = opts("chart", o), box = { x: 180, y: 760, w: FILM.W - 340, h: 560, ...o.box };
  const max = o.max || Math.max(...data), n = data.length, bw = Math.min(110, (box.w / n) * 0.6), gap = n > 1 ? (box.w - n * bw) / (n - 1) : 0;
  let out = `<line x1="${box.x - 20}" y1="${box.y}" x2="${box.x + box.w + 20}" y2="${box.y}" stroke="var(--hair,#c9cfdb)" stroke-width="3"/>`;
  data.forEach((v, i) => {
    const p = spring(t, t0 + i * P.stagger, P.response, P.damping), x = box.x + i * (bw + gap), h = (v / max) * box.h;
    const fill = i === n - 1 ? "var(--accent,#3b6cf5)" : "var(--accent-soft,#9db5f7)";
    out += `<rect x="${x.toFixed(1)}" y="${(box.y - h * p).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0, h * p).toFixed(1)}" rx="10" fill="${fill}"/>`;
    out += `<text x="${(x + bw / 2).toFixed(1)}" y="${(box.y - h * p - 18).toFixed(1)}" text-anchor="middle" font-weight="700" font-size="30" fill="var(--ink,#1b1f29)" opacity="${clamp(p * 2).toFixed(3)}">${(o.format || Math.round)(v * clamp(p))}</text>`;
    if (o.labels) out += `<text x="${(x + bw / 2).toFixed(1)}" y="${box.y + 40}" text-anchor="middle" font-weight="600" font-size="24" fill="var(--ink2,#667)">${o.labels[i]}</text>`;
  });
  svg.innerHTML = out;
}

const auroraLayer = (k = "aurora", n = 4) =>
  `<div data-k="${k}" class="full" style="overflow:hidden;pointer-events:none">${'<div class="abs" style="border-radius:50%;mix-blend-mode:screen"></div>'.repeat(n)}</div>`;

function aurora(t, o, k = "aurora") {
  const P = opts("aurora", o), ph = (t / 8) * 2 * Math.PI * P.speed, sx = FILM.W / 1440, sy = FILM.H / 900;
  [...$[k].children].forEach((b, i) => {
    const x = (720 + Math.sin(ph + i * 1.7) * 520) * sx, y = (260 + Math.cos(ph * 0.7 + i) * 120 + i * 60) * sy, r = 520 * P.size * Math.max(sx, sy);
    Object.assign(b.style, { left: (x - r).toFixed(1) + "px", top: (y - r).toFixed(1) + "px", width: (2 * r).toFixed(1) + "px", height: (2 * r).toFixed(1) + "px",
      background: `radial-gradient(circle, ${P.colors[i % P.colors.length]} 0%, transparent 65%)`, opacity: (P.intensity * 0.8).toFixed(3) });
  });
}

function motionBlur(host, t, place, o) {
  const P = opts("motionBlur", o), n = FILM.preview ? 1 : P.samples, shutter = P.shutter / FILM.FPS;
  if (host.children.length !== n) {
    const proto = host.dataset.proto || host.innerHTML;
    host.dataset.proto = proto;
    host.innerHTML = Array.from({ length: n }, () => proto).join("");
  }
  [...host.children].forEach((el, i) => {
    place(el, n === 1 ? t : t - shutter / 2 + (shutter * i) / (n - 1));
    el.style.opacity = n === 1 ? "1" : ((1 / n) * P.gain).toFixed(3);
  });
}

function rackFocus(layers, t, t0, from, to, o) {
  const P = opts("rackFocus", o), f = lerp(from, to, prog(t, t0, P.shift, E.inOut));
  layers.forEach((el, i) => {
    const b = (Math.abs(i - f) / Math.max(1, layers.length - 1)) * P.maxBlur;
    el.style.filter = b > 0.2 ? `blur(${b.toFixed(2)}px)` : "";
  });
  return f;
}
