const SCREEN = { W: 1512, H: 982, R: 12 };
const WIN = { x: 156, y: 70, w: 1200, h: 780, r: 12 };
const LAPTOP = { bezel: 18, lidR: 26, deckH: 22, deckOver: 150, notchW: 190, notchH: 30 };
const FULL = { x: 0, y: 0, w: WIN.w, h: WIN.h, r: WIN.r };

const ARROW = `<svg width="26" height="26" viewBox="0 0 26 26"><path d="M3 2.5v18.2l4.6-4.4 3.1 7.2 3.3-1.4-3.1-7.1h6.4Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;

function desktopMarkup(appHtml, { name = "Appname", menu = ["File", "Edit", "View", "Window", "Help"], extra = "", icon = "", dock = 6, clock = "Tue 9:41" } = {}) {
  const tile = (i) => `<div style="width:46px;height:46px;border-radius:12px;background:var(--tile${i % 3})"></div>`;
  const tray = `<svg width="22" height="12" viewBox="0 0 22 12"><rect x=".6" y=".6" width="18.4" height="10.8" rx="3" fill="none" stroke="currentColor" stroke-opacity=".55"/><rect x="2.4" y="2.4" width="12.5" height="7.2" rx="1.6" fill="currentColor"/><rect x="19.9" y="4" width="1.6" height="4" rx=".8" fill="currentColor" fill-opacity=".55"/></svg>`;
  return `
    <div class="cam" data-k="world">
      <div class="abs" data-k="deck" style="background:linear-gradient(180deg,var(--metal1),var(--metal2));box-shadow:0 20px 40px rgba(20,20,22,.18)"></div>
      <div class="abs" data-k="lid" style="left:0;top:0;width:${SCREEN.W}px;height:${SCREEN.H}px">
        <div class="abs" data-k="bezel" style="background:#0B0B0C;box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)"></div>
        <div class="abs" data-k="display" style="left:0;top:0;width:${SCREEN.W}px;height:${SCREEN.H}px;overflow:hidden">
          <div class="full" data-k="desk" style="background:radial-gradient(120% 90% at 30% 20%,var(--wall1),var(--wall2))">
            <div class="abs row" data-k="menubar" style="left:0;top:0;right:0;height:26px;padding:0 16px;gap:20px;font-size:13.5px;color:var(--menuInk);background:var(--menuBg)">
              <b>${name}</b>${menu.map((m) => `<span>${m}</span>`).join("")}
              <span class="row" style="margin-left:auto;gap:14px">${extra}${tray}<span>${clock}</span></span>
            </div>
            <div class="abs row" data-k="dock" style="left:50%;bottom:10px;height:62px;padding:0 8px;gap:8px;border-radius:18px;background:var(--dockBg);transform:translateX(-50%)">
              ${Array.from({ length: dock }, (_, i) => tile(i)).join("")}
              <div style="position:relative;width:46px;height:46px;border-radius:12px;overflow:hidden;background:var(--iconBg, var(--ink))">${icon}</div>
            </div>
          </div>
          <div class="abs" data-k="winShadow"></div>
          <div class="abs" data-k="win" style="left:${WIN.x}px;top:${WIN.y}px;width:${WIN.w}px;height:${WIN.h}px">
            <div class="abs" data-k="winClip" style="left:0;top:0;width:${WIN.w}px;height:${WIN.h}px;background:var(--winBg)">
              ${appHtml}
              <div class="abs row" data-k="lights" style="left:20px;top:20px;gap:8px">
                <i style="width:12px;height:12px;border-radius:50%;background:#FF5F57"></i>
                <i style="width:12px;height:12px;border-radius:50%;background:#FEBC2E"></i>
                <i style="width:12px;height:12px;border-radius:50%;background:#28C840"></i>
              </div>
            </div>
          </div>
          <div class="abs" data-k="pointer" style="left:0;top:0;width:26px;height:26px;transform-origin:3px 3px">${ARROW}</div>
        </div>
        <div class="abs" data-k="notch" style="background:#0B0B0C;border-radius:0 0 10px 10px"></div>
      </div>
    </div>`;
}

const view = (cx, cy, z) => ({ cx, cy, z });
const toStage = (v, x, y) => ({ x: FILM.W / 2 + (x - v.cx) * v.z, y: FILM.H / 2 + (y - v.cy) * v.z });
const onWindow = (x, y, z) => view(WIN.x + x, WIN.y + y, z);
const WHOLE_WINDOW = onWindow(WIN.w / 2, WIN.h / 2, 1.08);
const WHOLE_SCREEN = view(SCREEN.W / 2, SCREEN.H / 2 + 10, 0.86);
const WHOLE_LAPTOP = view(SCREEN.W / 2, SCREEN.H / 2 + 70, 0.74);

function cameraAt(t, keys) {
  const k0 = keys[0], rest = keys.slice(1).map((k) => ({ t: k.t, d: k.d, e: E.smooth, spring: k.d ? null : k.spring || [0.95, 1] }));
  const along = (f) => track(t, k0[f], rest.map((k, i) => ({ ...k, to: keys[i + 1][f] })));
  return view(along("cx"), along("cy"), along("z"));
}

function placeWorld(v, { rect = FULL, chrome = 1, desk = 1, hw = 0, lid = 1 } = {}) {
  setT($.world, `translate(${(FILM.W / 2 - v.cx * v.z).toFixed(2)}px,${(FILM.H / 2 - v.cy * v.z).toFixed(2)}px) scale(${v.z.toFixed(5)})`);
  $.winClip.style.clipPath = `inset(${rect.y.toFixed(2)}px ${(WIN.w - rect.x - rect.w).toFixed(2)}px ${(WIN.h - rect.y - rect.h).toFixed(2)}px ${rect.x.toFixed(2)}px round ${rect.r.toFixed(2)}px)`;
  rectCss($.winShadow, { x: WIN.x + rect.x, y: WIN.y + rect.y, w: rect.w, h: rect.h, r: rect.r });
  $.winShadow.style.boxShadow = `0 ${(24 * chrome).toFixed(2)}px ${(60 * chrome).toFixed(2)}px color-mix(in srgb, var(--shade, #0F0F14) ${(26 * chrome).toFixed(1)}%, transparent), 0 0 0 ${chrome > 0.01 ? 0.8 : 0}px var(--edge, rgba(0,0,0,.18))`;
  $.lights.style.opacity = chrome.toFixed(3);
  show($.winShadow, chrome > 0.001);

  const wx = WIN.x + rect.x, wy = WIN.y + rect.y;
  const inset = [wy, SCREEN.W - wx - rect.w, SCREEN.H - wy - rect.h, wx].map((v2) => (v2 * (1 - desk)).toFixed(2));
  $.desk.style.clipPath = `inset(${inset.join("px ")}px round ${lerp(rect.r, SCREEN.R, desk).toFixed(2)}px)`;
  show($.desk, desk > 0.001);

  const b = LAPTOP.bezel * hw;
  rectCss($.bezel, { x: -b, y: -b, w: SCREEN.W + 2 * b, h: SCREEN.H + 2 * b, r: SCREEN.R + (LAPTOP.lidR - SCREEN.R) * hw });
  $.display.style.borderRadius = `${SCREEN.R}px`;
  rectCss($.notch, { x: (SCREEN.W - LAPTOP.notchW) / 2, y: -1, w: LAPTOP.notchW, h: LAPTOP.notchH * hw, r: 0 });
  const over = LAPTOP.deckOver * hw;
  rectCss($.deck, { x: -b - over, y: SCREEN.H + b, w: SCREEN.W + 2 * (b + over), h: LAPTOP.deckH * hw, r: 0 });
  $.deck.style.borderRadius = `0 0 ${(28 * hw).toFixed(2)}px ${(28 * hw).toFixed(2)}px`;
  show($.bezel, hw > 0.001);
  show($.notch, hw > 0.001);
  show($.deck, hw > 0.001);
  $.lid.style.transformOrigin = `50% ${(SCREEN.H + b).toFixed(2)}px`;
  setT($.lid, lid >= 1 ? "none" : `perspective(2600px) rotateX(${(-90 * (1 - lid)).toFixed(3)}deg)`);
}

function pointerAt(t, keys, bow = 0.07) {
  let i = 0;
  while (i + 1 < keys.length && t >= keys[i + 1].t) i++;
  if (i === 0) return { x: keys[0].x, y: keys[0].y };
  const from = pointerAt(keys[i].t, keys.slice(0, i), bow), k = keys[i];
  const p = prog(t, k.t, k.d ?? 0.5, E.smooth), dx = k.x - from.x, dy = k.y - from.y;
  const side = Math.sin(Math.PI * p) * bow;
  return { x: from.x + dx * p - dy * side, y: from.y + dy * p + dx * side };
}

function placePointer(t, keys, clicks = [], on = -Infinity, off = Infinity) {
  const visible = t >= on && t < off;
  show($.pointer, visible);
  if (!visible) return;
  const p = pointerAt(t, keys);
  const s = clicks.reduce((m, c) => m * press(t, c, 0.86), 1);
  setT($.pointer, `translate(${(p.x - 3).toFixed(2)}px,${(p.y - 3).toFixed(2)}px) scale(${s.toFixed(4)})`);
}

function browserBar(url, { tabs = [] } = {}) {
  const tab = (title, i) => `<div class="row" style="height:30px;padding:0 14px;border-radius:9px;font-size:13.5px;${i ? "color:var(--ink2)" : "background:var(--winBg);box-shadow:0 1px 3px rgba(0,0,0,.08)"}">${title}</div>`;
  return `
    <div class="abs row" style="left:0;top:0;width:${WIN.w}px;height:50px;padding:0 16px 0 96px;gap:10px;background:var(--side);box-shadow:inset 0 -1px 0 var(--hair)">
      <div class="row" style="gap:6px">${tabs.map(tab).join("")}</div>
      <div class="row" style="margin-left:auto;width:520px;height:32px;padding:0 14px;border-radius:9px;background:var(--winBg);font-size:14px;color:var(--ink2);box-shadow:inset 0 0 0 1px var(--hair)">${url}</div>
      <div style="width:60px"></div>
    </div>`;
}
