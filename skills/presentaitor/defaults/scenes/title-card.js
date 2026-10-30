const CARD = window.TITLE_CARD || { n: 1, title: "Chapter title", W: 1920, H: 1080, seconds: 2.5 };
film({ W: CARD.W, H: CARD.H, BPM: 120, BEATS: CARD.seconds * 2 });

function build(stage) {
  stage.innerHTML = `
    <div class="full center" style="background:var(--bg);flex-direction:column;gap:26px">
      <div class="mask" style="height:44px"><div data-k="kick" class="t kicker">CHAPTER ${String(CARD.n).padStart(2, "0")}</div></div>
      <div class="mask" style="height:136px"><div data-k="title" class="t" style="font-size:104px;font-weight:800;letter-spacing:-0.04em">${CARD.title}</div></div>
      ${ASSETS.img && ASSETS.img.logo ? `<img data-k="logo" src="${ASSETS.img.logo}" style="width:96px;height:96px;border-radius:50%;margin-top:24px">` : ""}
    </div>
    ${vignetteLayer(0.5)}
    ${grainLayer(0.08)}`;
  collect(stage);
  $.words = split($.title, "word", true);
}

function apply(t) {
  grain(t);
  const out = prog(t, FILM.DURATION - 0.35, 0.35, E.in);
  rise($.kick, prog(t, 0.15, 0.5, E.out));
  reveal($.words, t, 0.3);
  $.kick.style.opacity = $.title.style.opacity = (1 - out).toFixed(3);
  if ($.logo) $.logo.style.opacity = (prog(t, 0.7, 0.5, E.out) * (1 - out)).toFixed(3);
}
