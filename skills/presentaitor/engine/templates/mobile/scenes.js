film({ BPM: 120, BEATS: 28, holds: [[5.2, 3], [6.5, 3], [7.9, 3], [10.5, 2]] });

const APP = { name: "Appname", slogan: "Your money, in plain view.", balance: ["$2,480.00", "$2,467.50"] };
const ROWS = [["Coffee", "Card", "-$12.50", "var(--accent)"], ["Groceries", "Card", "-$64.30", "#E0A526"],
  ["Transit", "Card", "-$2.75", "#3D7BE0"], ["Salary", "Account", "+$3,200.00", "#8A62D6"]];
const ICON = { pts: 128, px: 200 };
const CAMS = { phone: camAt(1.5, -43), left: { s: 1.2, x: 170, y: (FILM.H - PHONE.H * 1.2) / 2 } };
const WM = { size: 188, baseline: 680 };

function build(stage) {
  const row = ([title, sub, amount, color], i) => `
    <div class="abs" data-k="row${i}" style="left:0;top:0;width:362px;height:68px">
      <div class="abs" data-k="sep${i}" style="left:74px;right:0;top:0;height:1px;background:var(--hair)"></div>
      <div class="abs center" style="left:16px;top:12px;width:44px;height:44px;border-radius:12px;background:${color};color:#fff;font-weight:700;font-size:18px">${title[0]}</div>
      <div class="abs" style="left:74px;top:14px"><span class="t" style="display:block;font-size:16.5px;font-weight:600">${title}</span><span class="t" style="display:block;font-size:13.5px;color:var(--ink3)">${sub}</span></div>
      <div class="abs t" style="right:16px;top:22px;font-size:16.5px;font-weight:600;color:${amount[0] === "+" ? "var(--accent)" : "var(--ink)"}">${amount}</div>
    </div>`;
  const app = `
    <div class="screen" style="background:var(--bg)"></div>
    <div class="screen" style="background:linear-gradient(90deg,var(--aura1),var(--aura2));-webkit-mask-image:linear-gradient(180deg,#000a 0%,#0000 55%);mask-image:linear-gradient(180deg,#000a 0%,#0000 55%)"></div>
    <div class="screen" data-k="home">
      <div class="abs mask" style="left:20px;top:64px;width:300px;height:44px"><div data-k="title" class="t" style="font-size:32px;font-weight:700">Wallet</div></div>
      <div class="abs mask" style="left:20px;top:128px;width:200px;height:21px"><div data-k="balLabel" class="t" style="font-size:15px;font-weight:500;color:var(--ink2)">Balance</div></div>
      <div class="abs mask" style="left:20px;top:150px;width:360px;height:66px"><div data-k="bal" class="abs" style="left:0;top:0;width:360px;height:66px"></div></div>
      <div class="abs card" data-k="list" style="left:20px;top:250px;width:362px;height:${4 * 68}px;overflow:hidden">${ROWS.map(row).join("")}</div>
      <div class="abs center" data-k="fab" style="left:318px;top:764px;width:64px;height:64px;border-radius:22px;background:var(--accent);color:#fff;font-size:34px;font-weight:300;box-shadow:0 10px 30px #1a2a1c33">+</div>
    </div>
    <div class="abs" data-k="sheet" style="left:0;top:470px;width:402px;height:404px;border-radius:32px 32px 0 0;background:var(--card);box-shadow:0 -8px 30px #1a2a1c1f">
      <div class="abs t" style="left:24px;top:24px;font-size:20px;font-weight:600">New expense</div>
      <div class="abs mask" style="left:24px;top:66px;width:300px;height:62px"><div data-k="amount" class="t" style="font-size:46px;font-weight:700">$12.50</div></div>
      <div class="abs center" style="left:24px;top:146px;height:36px;padding:0 16px;border-radius:999px;background:var(--accentSoft);font-size:15px;font-weight:600"><span class="t">Coffee</span></div>
      <div class="abs center" data-k="save" style="left:24px;top:300px;width:354px;height:52px;border-radius:999px;background:var(--ink);color:#fff;font-size:18px;font-weight:600"><span class="t">Save</span></div>
    </div>
    <div class="abs" data-k="tap" style="width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;background:#ffffff57;box-shadow:0 0 0 2.5px #151a1680"></div>
    <div class="screen center" data-k="appIcon" style="background:var(--ink);color:var(--accent);font-size:${PHONE.W * 0.5}px;font-weight:800">${APP.name[0]}</div>`;
  stage.innerHTML = `
    <div class="full" style="background:var(--bg)"></div>
    ${deviceMarkup(app)}
    <div class="full" data-k="caption">
      <div class="abs mask" style="left:760px;top:560px;width:600px;height:32px"><div data-k="cap0" class="t" style="font-size:21px;font-weight:600;letter-spacing:.12em;color:var(--ink3)">YOUR APP</div></div>
      <div class="abs mask" style="left:760px;top:600px;width:660px;height:84px"><div data-k="cap1" class="t" style="font-size:66px;font-weight:700;letter-spacing:-.025em;line-height:78px">Say what it does</div></div>
      <div class="abs mask" style="left:760px;top:678px;width:660px;height:84px"><div data-k="cap2" class="t" style="font-size:66px;font-weight:700;letter-spacing:-.025em;line-height:78px">in one line.</div></div>
    </div>
    <div class="full" data-k="word">
      <div class="abs mask" data-k="wmClip" style="height:${WM.size * 1.3}px"><div data-k="wm" class="t" style="font-size:${WM.size}px;font-weight:700;letter-spacing:-.035em;line-height:1.3">${APP.name}</div></div>
      <div class="abs mask" data-k="slClip" style="height:60px"><div data-k="sl" class="t" style="font-size:42px;font-weight:500;color:var(--ink2);line-height:58px">${APP.slogan}</div></div>
      <div class="abs center" data-k="icon" style="overflow:hidden;background:var(--ink);color:var(--accent);font-weight:800">${APP.name[0]}
        <div class="abs" data-k="iconDot" style="left:50%;top:50%;border-radius:50%;background:var(--accent)"></div></div>
      <div class="abs" data-k="dot" style="width:36px;height:36px;margin:-18px 0 0 -18px;border-radius:50%;background:var(--accent)"></div>
    </div>`;
  collect(stage);
  $.balRoll = roller($.bal, "font-size:48px;font-weight:600;letter-spacing:-.4px");

  const textW = measure(APP.name, WM.size, 700, "letter-spacing:-.035em");
  const dot = 0.19 * WM.size, gap = 0.06 * WM.size;
  WM.left = Math.round((FILM.W - (textW + gap + dot)) / 2);
  WM.top = Math.round(WM.baseline - WM.size * 0.98);
  WM.textW = textW;
  Object.assign($.wmClip.style, { left: WM.left + "px", top: WM.top + "px", width: textW + 8 + "px" });
  WM.dotX = Math.round(WM.left + textW + gap + dot / 2);
  WM.dotY = Math.round(WM.baseline - dot / 2 - 1);
  const slW = measure(APP.slogan, 42, 500);
  Object.assign($.slClip.style, { left: Math.round((FILM.W - slW) / 2) + "px", top: WM.baseline + 58 + "px", width: slW + 4 + "px" });
}

function apply(t) {
  applyWord(t);
  applyDevice(t);
  applyApp(t);
  applyCaption(t);
}

function applyWord(t) {
  const gather = prog(t, B(2), 0.42, E.in);
  const back = spring(t, B(15.5), 0.5, 0.86);
  const inWord = t < B(2) + 0.45 || t >= B(15.5);
  show($.wm, inWord);
  $.wmClip.style.clipPath = t < B(15.5) ? `inset(0 ${((WM.textW + 8) * gather).toFixed(2)}px 0 0)` : "none";
  setT($.wm, `translateY(${(t >= B(15.5) ? (1 - clamp(back, 0, 1.2)) * 110 : 0).toFixed(2)}%)`);
  const slIn = spring(t, B(16), 0.5, 0.88);
  setT($.sl, TRAVEL(t >= B(16) ? 1 - slIn : prog(t, B(2), 0.3, E.in)));
  show($.slClip, t < B(3) || t >= B(16));

  let x = WM.dotX, y = WM.dotY, s = 1 + 0.1 * pulse(t, B(1), 0.32), on = true;
  if (t >= B(3) && t < B(3) + 0.75) {
    const p = prog(t, B(3), 0.5, E.smooth);
    x = lerp(WM.dotX, FILM.W / 2, p);
    y = lerp(WM.dotY, FILM.H / 2, p) - Math.sin(Math.PI * p) * 110;
    s = 1 - prog(t, B(3) + 0.5, 0.25, E.in);
  } else if (t >= B(15)) {
    const p = prog(t, B(15), FILM.P * 0.95, E.smooth);
    x = lerp(FILM.W / 2, WM.dotX, p);
    y = lerp(FILM.H / 2, WM.dotY, p) - Math.sin(Math.PI * p) * 70;
  } else if (t >= B(3)) on = false;
  show($.dot, on);
  setT($.dot, T(x, y, s));

  const iconOn = t >= B(13) + 0.44 && t < B(15);
  show($.icon, iconOn);
  if (iconOn) {
    const k = prog(t, B(14), 0.34, E.inOut);
    const size = lerp(ICON.px, 36, k);
    rectCss($.icon, { x: FILM.W / 2 - size / 2, y: FILM.H / 2 - size / 2, w: size, h: size, r: lerp(ICON.px * 0.2237, size / 2, k) });
    $.icon.style.fontSize = (size * 0.5).toFixed(2) + "px";
    const d = prog(t, B(14) + 0.08, 0.26, E.inOut) * size;
    rectCss($.iconDot, { x: 0, y: 0, w: d, h: d, r: d / 2 });
    $.iconDot.style.margin = `${-d / 2}px 0 0 ${-d / 2}px`;
    $.iconDot.style.left = $.iconDot.style.top = "50%";
  }
}

function applyDevice(t) {
  const on = t >= B(3) + 0.45 && t < B(13) + 0.46;
  show($.device, on);
  if (!on) return;
  const dotRect = { x: PHONE.W / 2 - 12, y: PHONE.H / 2 - 12, w: 24, h: 24, r: 12 };
  const close = prog(t, B(13), 0.45, E.inOut), crop = prog(t, B(13) + 0.2, 0.25, E.in);
  const square = { x: 0, y: (PHONE.H - PHONE.W) / 2, w: PHONE.W, h: PHONE.W, r: PHONE.W * 0.2237 };
  const rect = t < B(13) ? mixRect(dotRect, FULL, prog(t, B(3) + 0.5, 0.6, E.smooth)) : mixRect(FULL, square, crop);
  const edge = t < B(13) ? prog(t, B(3) + 0.55, 0.4, E.out) : 1 - prog(t, B(13) + 0.05, 0.3, E.in);
  const buttons = t < B(13) ? prog(t, B(3) + 0.8, 0.3, E.out) : 1 - prog(t, B(13), 0.2, E.in);
  let cam = cameraAt([
    { t0: 0, d: 0, cam: CAMS.phone, rest: B(4.5) },
    { t0: B(8), d: 0.8, cam: CAMS.left },
  ], t);
  if (t >= B(13)) {
    const s = lerp(cam.s, ICON.px / ICON.pts, close) * lerp(1, ICON.pts / PHONE.W, close);
    const cx = lerp(cam.x + (PHONE.W / 2) * cam.s, FILM.W / 2, close), cy = lerp(cam.y + (PHONE.H / 2) * cam.s, FILM.H / 2, close);
    cam = { s, x: cx - (PHONE.W / 2) * s, y: cy - (PHONE.H / 2) * s };
  }
  placeDevice(cam, rect, edge, buttons);
}

function applyApp(t) {
  rise($.title, prog(t, B(4) + 0.65, 0.4, E.out));
  rise($.balLabel, prog(t, B(4) + 0.73, 0.4, E.out));
  roll($.balRoll, t, [{ t: B(4) + 0.81, v: APP.balance[0] }, { t: B(7) + 0.35, v: APP.balance[1] }]);

  const shift = prog(t, B(7) + 0.1, 0.42, E.snappy);
  ROWS.forEach((_, i) => {
    const slot = i === 0 ? 0 : i - 1 + shift;
    const enter = i === 0 ? prog(t, B(7) + 0.2, 0.4, E.out) : prog(t, B(4.5) + 0.55 + i * 0.06, 0.45, E.out);
    $["row" + i].style.transform = `translate(${i === 0 ? ((1 - enter) * -40).toFixed(2) : 0}px,${(slot * 68 + (i ? (1 - enter) * 50 : 0)).toFixed(2)}px)`;
    show($["row" + i], i === 0 ? t >= B(7) + 0.2 : t >= B(4.5) + 0.55 + i * 0.06);
    show($["sep" + i], slot > 0.01);
  });
  $.list.style.clipPath = `inset(0 0 ${((1 - prog(t, B(4.5) + 0.5, 0.5, E.smooth)) * 100).toFixed(2)}% 0 round 24px)`;
  const fabIn = t < B(7) ? spring(t, B(5) + 0.5, 0.42, 0.62) : spring(t, B(7) + 0.45, 0.42, 0.62);
  show($.fab, t < B(6) + 0.3 || t >= B(7) + 0.45);
  setT($.fab, `scale(${(clamp(fabIn, 0, 1.2) * press(t, B(6), 0.9)).toFixed(4)})`);

  const up = (1 - spring(t, B(6) + 0.12, 0.5, 0.9)) * 404 + prog(t, B(7) + 0.05, 0.4, E.in) * 404;
  show($.sheet, t >= B(6) + 0.12 && t < B(7) + 0.46);
  setT($.sheet, `translateY(${up.toFixed(2)}px)`);
  rise($.amount, prog(t, B(6) + 0.35, 0.35, E.out));
  setT($.save, `scale(${press(t, B(7), 0.95).toFixed(4)})`);

  const taps = [[B(6), 350, 796], [B(7), 201, 796]];
  const tap = taps.find(([at]) => t >= at - 0.08 && t < at + 0.34);
  show($.tap, !!tap);
  if (tap) {
    const out = prog(t, tap[0] + 0.14, 0.2, E.out);
    Object.assign($.tap.style, { left: tap[1] + "px", top: tap[2] + "px", opacity: (1 - out).toFixed(3) });
    setT($.tap, `scale(${((0.6 + 0.4 * clamp(spring(t, tap[0] - 0.08, 0.22, 0.8), 0, 1.1)) * (1 + 0.35 * out)).toFixed(4)})`);
  }

  const iris = prog(t, B(13), 0.35, E.inOut);
  show($.appIcon, t > B(13));
  $.appIcon.style.clipPath = `circle(${(iris * Math.hypot(PHONE.W, PHONE.H) / 2).toFixed(2)}px at 50% 50%)`;
}

function applyCaption(t) {
  const on = t >= B(9) && t < B(13);
  show($.caption, on);
  if (!on) return;
  [["cap0", B(9)], ["cap1", B(9.5)], ["cap2", B(10)]].forEach(([key, at], i) => {
    const y = t < B(12) ? (1 - spring(t, at, 0.5, 0.88)) * 110 : prog(t, B(12) + (2 - i) * 0.05, 0.3, E.in) * -110;
    setT($[key], `translateY(${y.toFixed(2)}%)`);
  });
}
