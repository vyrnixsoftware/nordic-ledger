#!/usr/bin/env python3
"""One command per video:  python3 pipeline/run.py scripts/001-northvolt.md [--upload] [--publish-at ISO8601] [--fast]

Steps: parse -> TTS per scene (cached) -> render keyframes -> ffmpeg -> thumbnails -> metadata/srt -> (optional) upload.
Outputs in out/<id>-<slug>/ : video.mp4, audio.wav, thumb_A.jpg, thumb_B.jpg, metadata.json, description.txt, subtitles.srt, scenes.json
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time, hashlib
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent; ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from parse import parse_script, narration_words
from tts import synth
from render import Theme, build_video
from thumbnail import make_thumbnails
from metadata import write_metadata, write_srt


def load_cfg():
    return yaml.safe_load((HERE / "config.yaml").read_text())


def compliance_check(script) -> list[str]:
    """Pre-publish guardrails from the plan (section 6). Hard-fail on missing sources / too few scene types."""
    problems = []
    if not script.sources: problems.append("no SOURCES list")
    types = {s.type for s in script.scenes}
    if len(types) < 4: problems.append(f"only {len(types)} scene types – too templated")
    if not script.chapters: problems.append("no CHAPTERS block")
    words = narration_words(script)
    if words < 1200: problems.append(f"narration too short ({words} words)")
    banned = ["but here's the thing", "in a world where", "let's dive in", "game-changer", "game changer", "buckle up"]
    text = " ".join(s.narration.lower() for s in script.scenes)
    for b in banned:
        if b in text: problems.append(f"cliché found: '{b}'")
    for s in script.scenes:
        n = len(s.narration.split())
        if n > 185: problems.append(f"scene {s.n} narration long ({n} words) – split it")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script"); ap.add_argument("--upload", action="store_true"); ap.add_argument("--publish-at", default=None)
    ap.add_argument("--fast", action="store_true", help="ffmpeg ultrafast preset (dev)"); ap.add_argument("--force-tts", action="store_true")
    a = ap.parse_args()
    cfg = load_cfg(); t0 = time.time()
    script = parse_script(a.script)
    probs = compliance_check(script)
    if probs:
        print("COMPLIANCE CHECK FAILED:\n  - " + "\n  - ".join(probs)); sys.exit(2)
    out = ROOT / "out" / f"{script.id}-{script.slug}"; out.mkdir(parents=True, exist_ok=True)
    work = out / "work"; work.mkdir(exist_ok=True)
    th = Theme(cfg.get("style", {}), ROOT)

    # 1. TTS (cache by narration hash)
    print(f"[{script.id}] {script.title}  – {len(script.scenes)} scenes, {narration_words(script)} words")
    wavs = []
    for sc in script.scenes:
        h = hashlib.sha1((sc.narration + json.dumps(cfg["voice"], sort_keys=True)).encode()).hexdigest()[:12]
        wav = work / f"s{sc.n:02d}_{h}.wav"
        if not wav.exists() or a.force_tts:
            print(f"  tts scene {sc.n:02d} …", end="", flush=True)
            synth(sc.narration, wav, cfg["voice"]); print(" ok")
        import wave
        with wave.open(str(wav)) as w: sc.duration = w.getnframes() / w.getframerate()
        pad = float(cfg.get("timing", {}).get("scene_pad", 1.1))
        sc.duration += pad; sc.audio = str(wav); wavs.append((wav, pad))
    # concat audio with pads
    lst = work / "audio_concat.txt"
    with open(lst, "w") as f:
        for wav, pad in wavs:
            f.write(f"file '{wav.as_posix()}'\n")
            f.write(f"file '{(work / 'pad.wav').as_posix()}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(wavs[0][1]), str(work / "pad.wav")], check=True)
    audio = out / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1", str(audio)], check=True)
    total_planned = sum(s.duration for s in script.scenes)

    # 2. video
    print(f"  rendering ~{total_planned/60:.1f} min …", flush=True)
    rcfg = {"preset": "ultrafast" if a.fast else cfg.get("render", {}).get("preset", "medium")}
    mp4 = out / "video.mp4"
    total = build_video(script, th, work, mp4, audio, rcfg)

    # 3. thumbnails, metadata, srt
    thumbs = make_thumbnails(th, script, out)
    write_srt(script, out)
    write_metadata(script, cfg, out, total, thumbs[0])
    (out / "scenes.json").write_text(json.dumps([{"n": s.n, "type": s.type, "start": round(s.start, 2), "dur": round(s.duration, 2)} for s in script.scenes], indent=1))
    print(f"  done in {time.time()-t0:.0f}s → {mp4}  ({total/60:.1f} min)")

    # 4. upload
    if a.upload:
        from upload import upload_video, set_thumbnail, add_captions
        meta = json.loads((out / "metadata.json").read_text())
        vid = upload_video(mp4, meta, a.publish_at); print("  uploaded:", f"https://youtu.be/{vid}")
        set_thumbnail(vid, thumbs[0]); add_captions(vid, out / "subtitles.srt")
        (out / "upload.json").write_text(json.dumps({"video_id": vid, "publish_at": a.publish_at, "uploaded": time.time()}))


if __name__ == "__main__":
    main()
