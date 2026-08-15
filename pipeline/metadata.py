"""Build title/description/tags/chapters JSON for upload."""
from __future__ import annotations
import json, re
from pathlib import Path
from parse import Script

AI_LINE = ("The Nordic Ledger is an independent channel. This script was researched, written and edited with human editorial "
           "judgement; AI tools were used to assist with research, drafting and production. The narration is an AI-generated voice. "
           "If you spot an error, tell us in the comments and we will pin a correction.")


def mmss(t: float) -> str:
    t = int(round(t)); h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters_text(script: Script) -> list[tuple[float, str]]:
    out = []
    for scn, title in script.chapters:
        s = next((x.start for x in script.scenes if x.n == scn), None)
        if s is not None: out.append((s, title))
    out.sort()
    if not out or out[0][0] > 0.5: out.insert(0, (0.0, "Intro"))
    else: out[0] = (0.0, out[0][1])
    return out


def build_description(script: Script, cfg: dict, next_video_url: str | None = None) -> str:
    ch = cfg.get("channel", {})
    hook = script.meta.get("description_hook", "").strip()
    lines = [hook, ""]
    lines.append("▶ Chapters")
    for s, t in chapters_text(script): lines.append(f"{mmss(s)} {t}")
    lines += ["", "▶ How this video was made", AI_LINE, "", "▶ Sources"]
    for i, s in enumerate(script.sources, 1): lines.append(f"{i}. {s}")
    lines += ["", "▶ Disclosure", "This video contains no sponsorship or paid promotion.",
              "Nothing in this video is financial, legal or investment advice.", "", f"▶ {ch.get('name', 'The Nordic Ledger')}"]
    if ch.get("url"): lines.append(f"Subscribe: {ch['url']}?sub_confirmation=1")
    if next_video_url: lines.append(f"Watch next: {next_video_url}")
    if ch.get("contact"): lines.append(f"Business & press: {ch['contact']}")
    tags = script.meta.get("tags", [])[:3]
    lines += ["", " ".join("#" + re.sub(r"[^A-Za-z0-9]", "", t.title()) for t in tags) + " #BusinessDocumentary #TheNordicLedger"]
    desc = "\n".join(lines)
    return desc[:4990]


def build_tags(script: Script) -> list[str]:
    tags = list(dict.fromkeys(script.meta.get("tags", []) + ["business documentary", "nordic ledger", "corporate history", "europe business"]))
    out, total = [], 0
    for t in tags:
        t = str(t).replace("-", " ")
        if total + len(t) + 2 > 480: break
        out.append(t); total += len(t) + 2
    return out


def write_metadata(script: Script, cfg: dict, out_dir: Path, video_len: float, thumb: Path | None):
    meta = {
        "id": script.id, "slug": script.slug,
        "title": script.title, "title_options": script.meta.get("title_options", [script.title]),
        "description": build_description(script, cfg),
        "tags": build_tags(script),
        "categoryId": "27",  # Education (Business docs perform as Education/News; 27=Education)
        "defaultLanguage": "en", "defaultAudioLanguage": "en",
        "privacyStatus": cfg.get("upload", {}).get("privacy", "private"),
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": bool(script.meta.get("synthetic_label", False)),
        "durationSeconds": round(video_len, 1),
        "chapters": [(mmss(s), t) for s, t in chapters_text(script)],
        "thumbnail": str(thumb) if thumb else None,
    }
    p = out_dir / "metadata.json"; p.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "description.txt").write_text(meta["description"], encoding="utf-8")
    return p


def write_srt(script: Script, out_dir: Path):
    """Coarse subtitles: one cue per sentence, timed proportionally by word count within each scene."""
    def ts(t):
        h, r = divmod(t, 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    cues = []
    for sc in script.scenes:
        sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", sc.narration) if x.strip()]
        words = sum(len(x.split()) for x in sents) or 1
        t = sc.start + 0.2
        for s in sents:
            d = (len(s.split()) / words) * (sc.duration - 0.4)
            cues.append((t, t + d, s)); t += d
    with open(out_dir / "subtitles.srt", "w", encoding="utf-8") as f:
        for i, (a, b, s) in enumerate(cues, 1):
            f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{s}\n\n")
