"""1280x720 thumbnails: big serif headline (≤5 words), one accent number/word, brand tag. Two variants (A/B)."""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw
from render import Theme, wrap

TW, TH = 1280, 720


def _draw(th: Theme, big: str, small: str, accent_word: str | None, variant: int, out: Path):
    im = Image.new("RGB", (TW, TH), th.bg if variant == 0 else (18, 20, 26))
    d = ImageDraw.Draw(im)
    # diagonal accent block on the right for variant 1
    if variant == 1:
        d.polygon([(TW * 0.62, 0), (TW, 0), (TW, TH), (TW * 0.52, TH)], fill=(th.accent[0] // 4, th.accent[1] // 4, th.accent[2] // 4))
    d.text((60, 44), th.brand, font=th.font("bold", 26), fill=th.accent)
    size = 118
    while size > 60:
        f = th.font("head", size); lines = wrap(d, big, f, TW - 120 if variant == 0 else TW * 0.62)
        if len(lines) <= 3: break
        size -= 8
    y = 150 if variant == 0 else 130
    for ln in lines:
        # accent-colour a keyword if present
        if accent_word and accent_word.lower() in ln.lower():
            i = ln.lower().index(accent_word.lower()); pre, key, post = ln[:i], ln[i:i + len(accent_word)], ln[i + len(accent_word):]
            x = 60
            for part, col in ((pre, th.fg), (key, th.accent), (post, th.fg)):
                d.text((x, y), part, font=f, fill=col); x += d.textlength(part, font=f)
        else:
            d.text((60, y), ln, font=f, fill=th.fg)
        y += int(size * 1.08)
    d.line([(60, y + 26), (300, y + 26)], fill=th.accent, width=6)
    fs = th.font("body", 40)
    for ln in wrap(d, small, fs, TW - 120)[:2]:
        d.text((60, y + 60), ln, font=fs, fill=th.muted); y += 50
    im.save(out, quality=92)


def make_thumbnails(th: Theme, script, out_dir: Path) -> list[Path]:
    t = script.meta.get("thumb", {}) or {}
    big = t.get("big") or script.title.split(":")[0]
    small = t.get("small") or (script.title.split(":")[1].strip() if ":" in script.title else "")
    acc = t.get("accent")
    outs = []
    for v in (0, 1):
        p = out_dir / f"thumb_{'A' if v == 0 else 'B'}.jpg"; _draw(th, big, small, acc, v, p); outs.append(p)
    return outs
