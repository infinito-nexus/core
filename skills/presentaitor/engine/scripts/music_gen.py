import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("MOTION_DESIGNER_HOME", Path.home() / ".cache/motion-designer"))
ACE = Path(os.environ.get("MOTION_DESIGNER_ACESTEP", HOME / "ACE-Step-1.5"))
URL = os.environ.get("MOTION_DESIGNER_ACESTEP_URL", "").rstrip("/")
KEY = os.environ.get("MOTION_DESIGNER_ACESTEP_KEY", "")
LM, DIT = "acestep-5Hz-lm-1.7B", "acestep-v15-turbo"
SECTIONS = ["Intro", "Verse", "Chorus", "Verse", "Chorus", "Outro"]
OUT = sys.stdout


def load(path):
    spec = json.loads(Path(path).read_text())
    base = Path(path).resolve().parent
    return spec, base / spec.get("out", "audio/source"), base / "out/music"


def lyrics(spec):
    return "\n\n".join(f"[{s}]\n[Instrumental]" for s in spec.get("sections", SECTIONS))


def meta(spec):
    return {"bpm": spec["bpm"], "keyscale": spec["key"], "timesignature": str(spec.get("beats_per_bar", 4)), "duration": spec["seconds"]}


def asked(spec, name):
    return {"caption": spec["takes"][name]["caption"], "seed": spec["takes"][name]["seed"], "sections": lyrics(spec), **meta(spec)}


def planned(spec, name, cache):
    about = cache / f"{name}.about.json"
    return (cache / f"{name}.codes").exists() and about.exists() and json.loads(about.read_text()).get("asked") == asked(spec, name)


def language_model():
    from acestep.llm_inference import LLMHandler
    lm = LLMHandler()
    status, ok = lm.initialize(checkpoint_dir=str(ACE / "checkpoints"), lm_model_path=LM,
                               backend="mlx" if sys.platform == "darwin" else "vllm", device="auto")
    if not ok:
        raise SystemExit(f"ACE-Step's language model did not load: {status}")
    return lm


def diffusion_model():
    from acestep.handler import AceStepHandler
    dit = AceStepHandler()
    status, ok = dit.initialize_service(project_root=str(ACE), config_path=DIT, device="auto")
    if not ok:
        raise SystemExit(f"ACE-Step's diffusion model did not load: {status}")
    return dit


def hear(lm, codes):
    from acestep.inference import understand_music
    r = understand_music(lm, codes, temperature=0.3)
    if not r.success:
        return {"error": r.error}
    return {"caption": r.caption, "bpm": r.bpm, "key": r.keyscale, "vocals": r.language not in ("", "unknown")}


def plan(spec, names, cache):
    lm = language_model()
    for name in names:
        take, t0 = spec["takes"][name], time.time()
        r = lm.generate_with_stop_condition(
            caption=take["caption"], lyrics=lyrics(spec), infer_type="llm_dit", temperature=0.85, cfg_scale=2.0,
            negative_prompt="NO USER INPUT", top_k=None, top_p=0.9, target_duration=spec["seconds"], user_metadata=meta(spec),
            use_cot_caption=False, use_cot_language=False, use_cot_metas=False, use_constrained_decoding=True,
            constrained_decoding_debug=False, batch_size=1, seeds=[take["seed"]], progress=None)
        if not r.get("success"):
            raise SystemExit(f"{name}: the language model failed: {r.get('error')}")
        (cache / f"{name}.codes").write_text(r["audio_codes"])
        heard = hear(lm, r["audio_codes"])
        (cache / f"{name}.about.json").write_text(json.dumps({"asked": asked(spec, name), "hears": heard}, indent=1))
        print(f"{name}: planned in {time.time() - t0:.0f}s", file=OUT, flush=True)


def render(spec, names, cache, out):
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler
    dit = diffusion_model()
    for name in names:
        take, t0, m = spec["takes"][name], time.time(), meta(spec)
        params = GenerationParams(caption=take["caption"], lyrics=lyrics(spec), instrumental=True, vocal_language="unknown",
                                  bpm=m["bpm"], keyscale=m["keyscale"], timesignature=m["timesignature"], duration=float(m["duration"]),
                                  seed=take["seed"], audio_codes=(cache / f"{name}.codes").read_text(), thinking=False,
                                  use_cot_caption=False, use_cot_language=False, use_cot_metas=False)
        r = generate_music(dit, LLMHandler(), params, GenerationConfig(batch_size=1, use_random_seed=False, seeds=[take["seed"]], audio_format="wav"),
                           save_dir=str(cache / "tmp"))
        if not r.success:
            raise SystemExit(f"{name}: the diffusion model failed: {r.error}")
        shutil.move(r.audios[0]["path"], out / f"ace-{name}.wav")
        print(f"{name}: rendered in {time.time() - t0:.0f}s: {out / f'ace-{name}.wav'}", file=OUT, flush=True)
    shutil.rmtree(cache / "tmp", ignore_errors=True)


def encode(folder, files):
    dit = diffusion_model()
    for i, f in enumerate(files):
        codes = dit.convert_src_audio_to_codes(f)
        if not codes.startswith("<|audio_code_"):
            raise SystemExit(f"{f}: {codes}")
        (Path(folder) / f"{i}.codes").write_text(codes)


def describe(folder, files):
    lm = language_model()
    for i, f in enumerate(files):
        print(json.dumps({"file": f, **hear(lm, (Path(folder) / f"{i}.codes").read_text())}), file=OUT, flush=True)


def ace(*args, log):
    python = ACE / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"no ACE-Step in {ACE}: run setup_music.sh, or set MOTION_DESIGNER_ACESTEP_URL to a server")
    with open(log, "a") as err:
        p = subprocess.run([str(python), __file__, *map(str, args)], cwd=ACE, stderr=err)
    if p.returncode:
        raise SystemExit("\n".join(Path(log).read_text().splitlines()[-15:]) + f"\nACE-Step stopped; its log is {log}")


def remote(spec, names, out):
    def call(route, body=None):
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {KEY}"} if KEY else {})}
        data = json.dumps(body).encode() if body is not None else None
        with urllib.request.urlopen(urllib.request.Request(urllib.parse.urljoin(URL + "/", route), data=data, headers=headers), timeout=120) as r:
            return r.read()

    m, tasks, t0 = meta(spec), {}, time.time()
    for name in names:
        take = spec["takes"][name]
        body = {"prompt": take["caption"], "lyrics": lyrics(spec), "thinking": True, "vocal_language": "unknown",
                "bpm": m["bpm"], "key_scale": m["keyscale"], "time_signature": m["timesignature"], "audio_duration": m["duration"],
                "use_random_seed": False, "seed": take["seed"], "batch_size": 1, "audio_format": "wav",
                "use_cot_caption": False, "use_cot_language": False, "lm_temperature": 0.85, "lm_cfg_scale": 2.0, "lm_top_p": 0.9}
        tasks[json.loads(call("/release_task", body))["data"]["task_id"]] = name
    while tasks:
        time.sleep(2)
        for item in json.loads(call("/query_result", {"task_id_list": list(tasks)}))["data"]:
            if item["status"] == 0:
                continue
            name = tasks.pop(item["task_id"])
            if item["status"] != 1:
                raise SystemExit(f"{name}: the server failed: {item.get('result') or item}")
            (out / f"ace-{name}.wav").write_bytes(call(json.loads(item["result"])[0]["file"]))
            print(f"{name}: made on {URL} in {time.time() - t0:.0f}s: {out / f'ace-{name}.wav'}", flush=True)


def report(names, cache):
    for name in names:
        heard = json.loads((cache / f"{name}.about.json").read_text())["hears"]
        if "error" in heard:
            print(f"{name}: could not hear the plan: {heard['error']}")
        else:
            print(f"{name}: hears {heard['bpm']} BPM, {heard['key']}{', with vocals' if heard['vocals'] else ''}: {heard['caption']}")


def main():
    args = [a for a in sys.argv[1:] if a != "--plan-only"]
    if args[0] == "--hear":
        folder = tempfile.mkdtemp(prefix="motion-designer-hear-")
        files = [str(Path(f).resolve()) for f in args[1:]]
        ace("--encode", folder, *files, log=Path(folder) / "ace-step.log")
        ace("--describe", folder, *files, log=Path(folder) / "ace-step.log")
        shutil.rmtree(folder, ignore_errors=True)
        return
    spec, out, cache = load(args[0])
    names = args[1:] or list(spec["takes"])
    unknown = [n for n in names if n not in spec["takes"]]
    if unknown:
        raise SystemExit(f"no take {', '.join(unknown)} in {args[0]}; there are {', '.join(spec['takes'])}")
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    todo = [n for n in names if not (out / f"ace-{n}.wav").exists()]
    for n in names:
        if n not in todo:
            print(f"{n}: kept {out / f'ace-{n}.wav'}")
    if URL:
        if "--plan-only" in sys.argv:
            raise SystemExit("a server plans and renders in one go; hear its takes here with --hear")
        return remote(spec, todo, out) if todo else None
    log = cache / "ace-step.log"
    unplanned = [n for n in todo if not planned(spec, n, cache)]
    if unplanned:
        ace("--plan", Path(args[0]).resolve(), *unplanned, log=log)
    report(todo, cache)
    if "--plan-only" in sys.argv:
        print("render the takes that fit the sound brief: music_gen.py", args[0], "<take> ...")
    elif todo:
        ace("--render", Path(args[0]).resolve(), *todo, log=log)


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    if phase in ("--plan", "--render", "--encode", "--describe"):
        sys.stdout = sys.stderr
        sys.path.insert(0, str(ACE))
        if phase in ("--plan", "--render"):
            spec, out, cache = load(sys.argv[2])
            plan(spec, sys.argv[3:], cache) if phase == "--plan" else render(spec, sys.argv[3:], cache, out)
        else:
            (encode if phase == "--encode" else describe)(sys.argv[2], sys.argv[3:])
    else:
        main()
