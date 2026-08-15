"""Text-to-speech per scene. Providers: elevenlabs (API key), piper (offline CLI), edge (edge-tts), silence (dev).
Outputs 44.1kHz mono WAV per scene and returns duration in seconds.
"""
from __future__ import annotations
import os, json, shutil, subprocess, urllib.request, wave, struct, math, re
from pathlib import Path

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128"


def _wav_duration(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _to_wav(src: Path, dst: Path, speed: float = 1.0):
    af = f"atempo={speed}" if abs(speed - 1.0) > 0.01 else "anull"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", af,
                    "-ar", "44100", "-ac", "1", str(dst)], check=True)


def clean_for_tts(text: str) -> str:
    t = text.replace("—", ", ").replace("–", "-").replace(" ", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def tts_elevenlabs(text: str, out_wav: Path, voice_id: str, speed: float, api_key: str, model="eleven_multilingual_v2"):
    body = json.dumps({"text": text, "model_id": model,
                       "voice_settings": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.15, "use_speaker_boost": True}}).encode()
    req = urllib.request.Request(ELEVEN_URL.format(voice=voice_id), data=body,
                                 headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    mp3 = out_wav.with_suffix(".mp3")
    with urllib.request.urlopen(req, timeout=180) as r, open(mp3, "wb") as f:
        shutil.copyfileobj(r, f)
    _to_wav(mp3, out_wav, speed)


def tts_piper(text: str, out_wav: Path, model: str, speed: float):
    # piper --model en_GB-alan-medium.onnx --output_file x.wav ; length_scale >1 = slower
    length_scale = 1.0 / speed
    root = Path(__file__).resolve().parent.parent
    model_path = os.environ.get("PIPER_MODEL_PATH") or model
    if not Path(model_path).exists():
        cand = root / "assets" / "voices" / (model_path if model_path.endswith(".onnx") else model_path + ".onnx")
        if cand.exists(): model_path = str(cand)
    piper_bin = str(root / "assets" / "bin" / "piper" / "piper") if (root / "assets" / "bin" / "piper" / "piper").exists() else "piper"
    subprocess.run([piper_bin, "--model", model_path, "--length_scale", str(length_scale), "--output_file", str(out_wav)],
                   input=text.encode(), check=True, capture_output=True)
    tmp = out_wav.with_name(out_wav.stem + "_r.wav")
    _to_wav(out_wav, tmp, 1.0); shutil.move(tmp, out_wav)


def tts_edge(text: str, out_wav: Path, voice: str, speed: float):
    pct = int(round((speed - 1.0) * 100))
    mp3 = out_wav.with_suffix(".mp3")
    subprocess.run(["edge-tts", "--voice", voice, "--rate", f"{pct:+d}%", "--text", text, "--write-media", str(mp3)],
                   check=True, capture_output=True)
    _to_wav(mp3, out_wav, 1.0)


def tts_silence(text: str, out_wav: Path, wpm: float = 150.0):
    """Dev fallback: silence sized to ~150 wpm so timing/renders can be tested without a TTS engine."""
    secs = max(2.0, len(text.split()) / wpm * 60.0)
    sr = 44100; n = int(secs * sr)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        # very quiet pink-ish hiss so players don't treat it as empty
        frames = bytearray()
        for i in range(n):
            v = int(80 * math.sin(i * 0.013) * math.sin(i * 0.0007))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def synth(text: str, out_wav: Path, cfg: dict) -> float:
    out_wav = Path(out_wav); out_wav.parent.mkdir(parents=True, exist_ok=True)
    text = clean_for_tts(text)
    prov = cfg.get("provider", "auto"); speed = float(cfg.get("speed", 1.0))
    key = os.environ.get("ELEVENLABS_API_KEY")
    if prov == "auto":
        if key: prov = "elevenlabs"
        elif shutil.which("piper") or (Path(__file__).resolve().parent.parent / "assets" / "bin" / "piper" / "piper").exists(): prov = "piper"
        elif shutil.which("edge-tts"): prov = "edge"
        else: prov = "silence"
    if prov == "elevenlabs": tts_elevenlabs(text, out_wav, cfg["elevenlabs_voice_id"], speed, key)
    elif prov == "piper": tts_piper(text, out_wav, cfg.get("piper_model", "en_GB-alan-medium"), speed)
    elif prov == "edge": tts_edge(text, out_wav, cfg.get("edge_voice", "en-GB-RyanNeural"), speed)
    else: tts_silence(text, out_wav)
    return _wav_duration(out_wav)
