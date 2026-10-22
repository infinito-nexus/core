(function () {
  const params = new URLSearchParams(location.search);
  FILM.preview = params.has("preview");
  const stage = document.getElementById("stage");
  Object.assign(stage.style, { width: FILM.W + "px", height: FILM.H + "px" });

  const ready = (async () => {
    for (const f of ASSETS.fonts) document.fonts.add(await new FontFace(f.family, `url(${f.src})`, { weight: f.weight }).load());
    await document.fonts.ready;
    build(stage);
    window.FILM_CUES = typeof cues === "function" ? cues().map(([sound, t, o = {}]) => ({ sound, t: +t.toFixed(4), ...o })).sort((p, q) => p.t - q.t) : [];
    await Promise.all([...document.images].map((img) => (img.decode ? img.decode().catch(() => {}) : null)));
  })();

  window.seek = async function seek(t) {
    await ready;
    apply(Math.min(Math.max(0, t), FILM.DURATION));
  };
  window.FILM_INFO = { W: FILM.W, H: FILM.H, FPS: FILM.FPS, BPM: FILM.BPM, BEATS: FILM.BEATS, frames: FILM.frames };

  if (params.has("render")) {
    document.documentElement.classList.add("render");
    if (params.has("t")) seek(Number(params.get("t")));
    return;
  }

  const audio = document.getElementById("music");
  const scrub = document.getElementById("scrub");
  const play = document.getElementById("play");
  const time = document.getElementById("time");
  scrub.max = String(FILM.DURATION);
  let playing = false;
  let clock = 0;

  const fit = () => {
    const s = Math.min((innerWidth - 32) / FILM.W, (innerHeight - 96) / FILM.H);
    stage.style.transform = `scale(${s})`;
    stage.parentElement.style.width = FILM.W * s + "px";
    stage.parentElement.style.height = FILM.H * s + "px";
  };
  addEventListener("resize", fit);
  fit();

  const showAt = (t) => {
    seek(t);
    scrub.value = String(t);
    time.textContent = `${t.toFixed(2)} s · beat ${Math.min(Math.floor(t / FILM.P) + 1, FILM.BEATS)}`;
  };
  const hasMusic = () => audio && audio.readyState > 0 && !audio.error;
  const loop = (now) => {
    if (!playing) return;
    const t = hasMusic() ? audio.currentTime : (clock = (clock + (now - (loop.last ?? now)) / 1000) % FILM.DURATION);
    loop.last = now;
    showAt(t);
    requestAnimationFrame(loop);
  };
  play.addEventListener("click", async () => {
    await ready;
    playing = !playing;
    play.textContent = playing ? "Pause" : "Play";
    loop.last = undefined;
    if (playing) {
      if (hasMusic()) await audio.play().catch(() => {});
      requestAnimationFrame(loop);
    } else if (hasMusic()) audio.pause();
  });
  scrub.addEventListener("input", () => {
    clock = Number(scrub.value);
    if (hasMusic()) audio.currentTime = clock;
    if (!playing) showAt(clock);
  });
  if (audio) audio.addEventListener("ended", () => { audio.currentTime = 0; if (playing) audio.play(); });
  const start = Number(params.get("t") || 0);
  ready.then(() => { clock = start; if (hasMusic()) audio.currentTime = start; showAt(start); });
  document.getElementById("player").hidden = false;
})();
