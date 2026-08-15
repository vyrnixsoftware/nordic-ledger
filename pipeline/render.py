"""Render scenes to keyframe images + durations (concat-demuxer friendly), then assemble with ffmpeg.

Design: dark editorial look. Only frames where something changes are drawn (bullet reveals, bar growth,
timeline items), so a 15-minute video is a few hundred PNGs, not 27,000.
"""
from __future__ import annotations
import math, os, subprocess, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from parse import Scene, Script

W, H = 1920, 1080
FPS = 30
MARGIN = 120

DEFAULT_FONTS = {
    "head": ["assets/fonts/Fraunces-SemiBold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"],
    "body": ["assets/fonts/Inter-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "bold": ["assets/fonts/Inter-SemiBold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
}


def hexrgb(h): h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


class Theme:
    def __init__(self, style: dict, root: Path):
        p = style.get("palette", {})
        self.bg = hexrgb(p.get("bg", "#0E1116")); self.fg = hexrgb(p.get("fg", "#E8E6E1"))
        self.accent = hexrgb(p.get("accent", "#C8A24A")); self.accent2 = hexrgb(p.get("accent2", "#3C7DD9"))
        self.danger = hexrgb(p.get("danger", "#D0503C")); self.muted = (140, 144, 152); self.rail = (40, 44, 52)
        self.root = root
        self._cache = {}
        self.fontfiles = {}
        for k, cands in DEFAULT_FONTS.items():
            cands = ([style.get("font_" + k)] if style.get("font_" + k) else []) + cands
            for c in cands:
                pth = (root / c) if not str(c).startswith("/") else Path(c)
                if pth.exists(): self.fontfiles[k] = str(pth); break
        self.brand = style.get("brand", "THE NORDIC LEDGER")

    def font(self, kind, size):
        key = (kind, size)
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(self.fontfiles.get(kind, self.fontfiles["body"]), size)
        return self._cache[key]


# ---------- drawing helpers ----------
def split_bullets(s: str) -> list[str]:
    """Split on ';' but re-join fragments that start lowercase (a ';' used inside a sentence)."""
    out = []
    for b in (x.strip() for x in s.split(";")):
        if not b: continue
        if out and b[0].islower(): out[-1] = out[-1] + "; " + b
        else: out.append(b)
    return out


def wrap(draw, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw: cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines


def fit_font(draw, th, kind, text, maxw, maxh, start, minsize=28, line_gap=1.15):
    size = start
    while size > minsize:
        f = th.font(kind, size)
        lines = wrap(draw, text, f, maxw)
        if len(lines) * size * line_gap <= maxh: return f, lines
        size -= 4
    f = th.font(kind, minsize); return f, wrap(draw, text, f, maxw)


def base(th: Theme, scene_n=None, total=None):
    im = Image.new("RGB", (W, H), th.bg)
    d = ImageDraw.Draw(im)
    # subtle vignette-ish gradient band at top
    for i in range(0, 220, 4):
        a = int(18 * (1 - i / 220))
        d.line([(0, i), (W, i)], fill=(th.bg[0] + a, th.bg[1] + a, th.bg[2] + a + 2), width=4)
    # brand mark
    f = th.font("bold", 22)
    d.text((MARGIN, 52), th.brand, font=f, fill=th.accent)
    d.line([(MARGIN, 90), (MARGIN + 60, 90)], fill=th.accent, width=3)
    if scene_n and total:
        s = f"{scene_n:02d} / {total:02d}"
        d.text((W - MARGIN - d.textlength(s, font=f), 52), s, font=f, fill=th.muted)
    return im, d


def blend(a: Image.Image, b: Image.Image, t: float): return Image.blend(a, b, max(0, min(1, t)))


def ease(t): return 1 - (1 - t) ** 3


def fade_frames(im_from, im_to, secs, fps=FPS):
    n = max(1, int(secs * fps)); out = []
    for i in range(1, n + 1):
        out.append((blend(im_from, im_to, ease(i / n)), 1 / fps))
    return out


# ---------- scene renderers: return list[(Image, seconds)] summing to duration ----------
def sc_title(th, sc: Scene, dur, n, tot):
    im0, _ = base(th)
    im, d = base(th)
    title = sc.attrs.get("title", ""); sub = sc.attrs.get("subtitle", "")
    f, lines = fit_font(d, th, "head", title, W - 2 * MARGIN, 420, 112, 56)
    y = 330
    for ln in lines:
        d.text((MARGIN, y), ln, font=f, fill=th.fg); y += int(f.size * 1.12)
    d.line([(MARGIN, y + 24), (MARGIN + 180, y + 24)], fill=th.accent, width=4)
    if sub:
        fs = th.font("body", 40); d.text((MARGIN, y + 60), sub, font=fs, fill=th.muted)
    frames = fade_frames(im0, im, 1.2)
    frames.append((im, max(0.1, dur - 1.2)))
    return frames


def sc_text(th, sc: Scene, dur, n, tot):
    head = sc.attrs.get("headline", ""); bullets = split_bullets(sc.attrs.get("bullets", ""))
    im, d = base(th, n, tot)
    f, lines = fit_font(d, th, "head", head, W - 2 * MARGIN, 220, 72, 44)
    y = 150
    for ln in lines: d.text((MARGIN, y), ln, font=f, fill=th.fg); y += int(f.size * 1.12)
    y0 = y + 50
    d.line([(MARGIN, y0 - 20), (MARGIN + 120, y0 - 20)], fill=th.accent, width=3)
    avail = H - y0 - 90
    fb = th.font("body", 40 if len(bullets) <= 5 else 34)
    # pre-wrap bullets to compute heights
    wrapped = [wrap(d, b, fb, W - 2 * MARGIN - 60) for b in bullets]
    total_h = sum(len(w) * fb.size * 1.25 + 26 for w in wrapped)
    if total_h > avail:
        fb = th.font("body", 30); wrapped = [wrap(d, b, fb, W - 2 * MARGIN - 60) for b in bullets]
    frames = []
    prev = im.copy()
    frames.append((prev, min(1.2, dur * 0.12)))
    used = min(1.2, dur * 0.12)
    k = len(bullets)
    if k:
        span = dur * 0.72
        step = span / k
        y = y0
        for i, ws in enumerate(wrapped):
            cur = prev.copy(); dd = ImageDraw.Draw(cur)
            dd.ellipse([MARGIN, y + 16, MARGIN + 12, y + 28], fill=th.accent)
            yy = y
            for ln in ws: dd.text((MARGIN + 40, yy), ln, font=fb, fill=th.fg); yy += int(fb.size * 1.25)
            y = yy + 26
            fr = fade_frames(prev, cur, 0.35)
            frames += fr; used += sum(t for _, t in fr)
            hold = step - 0.35
            if hold > 0: frames.append((cur, hold)); used += hold
            prev = cur
    rest = dur - used
    if rest > 0: frames.append((prev, rest))
    return frames


def sc_quote(th, sc: Scene, dur, n, tot):
    im, d = base(th, n, tot)
    q = sc.attrs.get("text", ""); who = sc.attrs.get("attribution", "")
    d.text((MARGIN - 10, 170), "“", font=th.font("head", 260), fill=th.accent)
    f, lines = fit_font(d, th, "head", q, W - 2 * MARGIN - 40, 520, 64, 36)
    y = 400
    for ln in lines: d.text((MARGIN + 30, y), ln, font=f, fill=th.fg); y += int(f.size * 1.18)
    im2 = im.copy(); d2 = ImageDraw.Draw(im2)
    if who:
        fw = th.font("body", 34)
        wl = wrap(d2, "— " + who, fw, W - 2 * MARGIN - 40); yy = y + 40
        for ln in wl: d2.text((MARGIN + 30, yy), ln, font=fw, fill=th.muted); yy += 44
    im0, _ = base(th, n, tot)
    frames = fade_frames(im0, im, 0.8) + [(im, 1.6)] + fade_frames(im, im2, 0.5)
    frames.append((im2, max(0.1, dur - 2.9)))
    return frames


def _fmt(v):
    if abs(v) >= 100: return f"{v:,.0f}"
    if abs(v) >= 10: return f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{v:.2f}".rstrip("0").rstrip(".")


def sc_chart(th, sc: Scene, dur, n, tot):
    kind = sc.attrs.get("chart", "bar"); title = sc.attrs.get("title", "")
    rows = sc.data
    keys = list(rows[0].keys()) if rows else ["x", "value"]
    xk = keys[0]; ykeys = [k for k in keys[1:]] or ["value"]
    labels = [r[xk] for r in rows]
    series = []
    for yk in ykeys:
        vals = []
        for r in rows:
            try: vals.append(float(str(r[yk]).replace(",", "")))
            except: vals.append(0.0)
        series.append((yk, vals))
    im, d = base(th, n, tot)
    f, lines = fit_font(d, th, "head", title, W - 2 * MARGIN, 160, 54, 34)
    y = 140
    for ln in lines: d.text((MARGIN, y), ln, font=f, fill=th.fg); y += int(f.size * 1.12)
    top, bottom, left, right = y + 60, H - 170, MARGIN + 40, W - MARGIN
    vmax = max(max(v for _, vs in series for v in vs), 1e-9); vmin = min(0, min(v for _, vs in series for v in vs))
    span = vmax - vmin
    fl = th.font("body", 26); fm = th.font("mono", 24)
    # gridlines
    for g in range(5):
        gy = bottom - (bottom - top) * g / 4
        d.line([(left, gy), (right, gy)], fill=th.rail, width=1)
        d.text((left - 12 - d.textlength(_fmt(vmin + span * g / 4), font=fm), gy - 14), _fmt(vmin + span * g / 4), font=fm, fill=th.muted)
    static = im.copy()
    colors = [th.accent, th.accent2, th.danger, th.fg]
    frames = [(static, 0.4)]; used = 0.4
    anim = min(2.2, dur * 0.4); steps = int(anim * FPS)
    m = len(labels)
    if kind == "bar":
        gw = (right - left) / max(m, 1); bw = gw * (0.62 / len(series))
        for i in range(1, steps + 1):
            p = ease(i / steps); cur = static.copy(); dd = ImageDraw.Draw(cur)
            for j, lab in enumerate(labels):
                x0 = left + j * gw + gw * 0.19
                lx = left + j * gw + gw / 2
                fll = fl if m <= 12 else th.font("body", 20)
                t = str(lab); dd.text((lx - dd.textlength(t, font=fll) / 2, bottom + 14), t, font=fll, fill=th.muted)
                for si, (nm, vs) in enumerate(series):
                    v = vs[j] * p; hgt = (v - vmin) / span * (bottom - top)
                    zero = bottom - (0 - vmin) / span * (bottom - top)
                    xx = x0 + si * bw
                    dd.rectangle([xx, zero - hgt if v >= 0 else zero, xx + bw - 6, zero if v >= 0 else zero - hgt], fill=colors[si % 4])
                    if i == steps:
                        t = _fmt(vs[j]); dd.text((xx + (bw - 6) / 2 - dd.textlength(t, font=fm) / 2, (zero - hgt) - 34), t, font=fm, fill=th.fg)
            frames.append((cur, 1 / FPS)); used += 1 / FPS
    else:  # line
        pts_all = []
        for si, (nm, vs) in enumerate(series):
            pts = [(left + (right - left) * (j / max(m - 1, 1)), bottom - (v - vmin) / span * (bottom - top)) for j, v in enumerate(vs)]
            pts_all.append(pts)
        # x labels (thin out)
        dd0 = ImageDraw.Draw(static); every = max(1, math.ceil(m / 12))
        for j, lab in enumerate(labels):
            if j % every == 0 or j == m - 1:
                x = left + (right - left) * (j / max(m - 1, 1)); t = str(lab)
                dd0.text((x - dd0.textlength(t, font=fl) / 2, bottom + 14), t, font=fl, fill=th.muted)
        for i in range(1, steps + 1):
            p = ease(i / steps); cur = static.copy(); dd = ImageDraw.Draw(cur)
            for si, pts in enumerate(pts_all):
                upto = p * (len(pts) - 1); k = int(upto)
                seg = pts[:k + 1]
                if k < len(pts) - 1:
                    fr = upto - k; a, b = pts[k], pts[k + 1]
                    seg.append((a[0] + (b[0] - a[0]) * fr, a[1] + (b[1] - a[1]) * fr))
                if len(seg) > 1: dd.line(seg, fill=colors[si % 4], width=5, joint="curve")
                ex, ey = seg[-1]; dd.ellipse([ex - 8, ey - 8, ex + 8, ey + 8], fill=colors[si % 4])
                if i == steps:
                    t = _fmt(series[si][1][-1]); dd.text((ex + 14, ey - 16), t, font=fm, fill=th.fg)
            frames.append((cur, 1 / FPS)); used += 1 / FPS
    if len(series) > 1:
        last = frames[-1][0]; dd = ImageDraw.Draw(last); x = left
        for si, (nm, _) in enumerate(series):
            dd.rectangle([x, H - 110, x + 22, H - 88], fill=colors[si % 4]); dd.text((x + 32, H - 116), nm, font=fl, fill=th.fg)
            x += 60 + dd.textlength(nm, font=fl)
    rest = dur - used
    if rest > 0: frames.append((frames[-1][0], rest))
    return frames


def sc_timeline(th, sc: Scene, dur, n, tot):
    title = sc.attrs.get("title", ""); rows = sc.data
    im, d = base(th, n, tot)
    f, lines = fit_font(d, th, "head", title, W - 2 * MARGIN, 160, 54, 34)
    y = 140
    for ln in lines: d.text((MARGIN, y), ln, font=f, fill=th.fg); y += int(f.size * 1.12)
    y0 = y + 40; k = len(rows)
    avail = H - y0 - 70
    row_h = min(78, avail / max(k, 1))
    fs = 34 if row_h >= 60 else (28 if row_h >= 44 else 22)
    fd = th.font("mono", fs - 4); fb = th.font("body", fs)
    railx = MARGIN + 190
    d.line([(railx, y0), (railx, y0 + row_h * k)], fill=th.rail, width=3)
    frames = [(im.copy(), min(1.0, dur * 0.1))]; used = frames[0][1]
    span = dur * 0.78; step = span / max(k, 1)
    prev = im
    for i, r in enumerate(rows):
        vals = [v for v in r.values() if v is not None]
        flat = []
        for v in vals: flat += v if isinstance(v, list) else [v]
        date = flat[0] if flat else ""; label = ",".join(x for x in flat[1:] if x is not None)
        cur = prev.copy(); dd = ImageDraw.Draw(cur)
        yy = y0 + i * row_h + row_h / 2
        dd.line([(railx, y0), (railx, yy)], fill=th.accent, width=3)
        dd.ellipse([railx - 9, yy - 9, railx + 9, yy + 9], fill=th.accent)
        dd.text((railx - 30 - dd.textlength(date, font=fd), yy - fs / 2), date, font=fd, fill=th.muted)
        lab = label
        while dd.textlength(lab, font=fb) > W - railx - 40 - MARGIN and len(lab) > 10: lab = lab[:-2]
        if lab != label: lab = lab.rstrip() + "…"
        dd.text((railx + 30, yy - fs / 2 - 2), lab, font=fb, fill=th.fg)
        fr = fade_frames(prev, cur, 0.3); frames += fr; used += 0.3
        hold = step - 0.3
        if hold > 0: frames.append((cur, hold)); used += hold
        prev = cur
    rest = dur - used
    if rest > 0: frames.append((prev, rest))
    return frames


CITY = {  # lon, lat
    "stockholm": (18.07, 59.33), "skellefteå": (21.0, 64.75), "västerås": (16.55, 59.61), "gothenburg": (11.97, 57.71),
    "heide": (9.1, 54.2), "gdańsk": (18.65, 54.35), "gdansk": (18.65, 54.35), "helsinki": (24.94, 60.17), "espoo": (24.66, 60.21),
    "oslo": (10.75, 59.91), "copenhagen": (12.57, 55.68), "munich": (11.58, 48.14), "berlin": (13.4, 52.52), "frankfurt": (8.68, 50.11),
    "london": (-0.13, 51.51), "paris": (2.35, 48.86), "amsterdam": (4.9, 52.37), "vienna": (16.37, 48.21), "zurich": (8.54, 47.38),
    "milan": (9.19, 45.46), "madrid": (-3.7, 40.42), "warsaw": (21.01, 52.23), "tallinn": (24.75, 59.44), "riga": (24.1, 56.95),
    "vilnius": (25.28, 54.69), "dublin": (-6.26, 53.35), "aschheim": (11.72, 48.17), "manila": (120.98, 14.6), "dubai": (55.27, 25.2),
    "singapore": (103.82, 1.35), "moscow": (37.62, 55.75), "salo": (23.13, 60.39), "oulu": (25.47, 65.01), "tampere": (23.76, 61.5),
    "nokia": (23.51, 61.48), "montreal": (-73.57, 45.5), "san francisco": (-122.42, 37.77), "new york": (-74.0, 40.71),
    "erfurt": (11.03, 50.98), "debrecen": (21.63, 47.53), "zaragoza": (-0.88, 41.65), "ningde": (119.55, 26.66), "shenzhen": (114.06, 22.54),
    "hamburg": (9.99, 53.55), "lund": (13.19, 55.7), "malmö": (13.0, 55.6), "turku": (22.27, 60.45), "vaasa": (21.62, 63.1),
    "brussels": (4.35, 50.85), "luxembourg": (6.13, 49.61), "malta": (14.51, 35.9), "valletta": (14.51, 35.9), "kuala lumpur": (101.69, 3.14),
    "jakarta": (106.85, -6.21), "tokyo": (139.69, 35.69), "seoul": (126.98, 37.57), "chicago": (-87.63, 41.88), "sunnyvale": (-122.04, 37.37),
    "san jose": (-121.89, 37.34), "espoo ": (24.66, 60.21), "geneva": (6.14, 46.2), "lisbon": (-9.14, 38.72), "prague": (14.42, 50.09),
    "budapest": (19.04, 47.5), "athens": (23.73, 37.98), "rome": (12.5, 41.9), "reykjavik": (-21.94, 64.15), "tromsø": (18.96, 69.65),
    "kirkenes": (30.05, 69.73), "murmansk": (33.08, 68.97), "st petersburg": (30.32, 59.93), "brno": (16.6, 49.2), "bratislava": (17.11, 48.15),
    "manchester": (-2.24, 53.48), "edinburgh": (-3.19, 55.95), "birmingham": (-1.9, 52.48), "wuxi": (120.3, 31.57), "shanghai": (121.47, 31.23),
    "beijing": (116.4, 39.9), "hong kong": (114.17, 22.32), "kyiv": (30.52, 50.45), "istanbul": (28.98, 41.01), "cairo": (31.24, 30.04),
    "tel aviv": (34.78, 32.09), "delhi": (77.21, 28.61), "mumbai": (72.88, 19.08), "sydney": (151.21, -33.87), "toronto": (-79.38, 43.65),
    "quebec": (-71.21, 46.81), "seattle": (-122.33, 47.61), "los angeles": (-118.24, 34.05), "boston": (-71.06, 42.36), "washington": (-77.04, 38.9),
    "tashkent": (69.24, 41.3), "gibraltar": (-5.35, 36.14), "almaty": (76.89, 43.24), "baku": (49.87, 40.41), "kathmandu": (85.32, 27.72),
    "tbilisi": (44.83, 41.72), "dushanbe": (68.78, 38.56), "the hague": (4.3, 52.08), "solna": (18.0, 59.36),
}
REGIONS = {"nordics": (0, 45, 35, 71), "europe": (-12, 34, 42, 71), "world": (-130, -40, 150, 72), "germany": (5, 46, 16, 56)}


def _project(lon, lat, box):
    x0, y0, x1, y1 = box
    # simple equirectangular with lat stretch (Mercator-lite)
    def my(la): return math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    px = (lon - x0) / (x1 - x0); py = (my(y1) - my(lat)) / (my(y1) - my(y0))
    return px, py


def sc_map(th, sc: Scene, dur, n, tot):
    region = sc.attrs.get("region", "europe").lower(); markers = [m.strip() for m in sc.attrs.get("markers", "").split(";") if m.strip()]
    coords = []
    for m in markers:
        c = CITY.get(m.lower())
        if c: coords.append((m, c))
    box = REGIONS.get(region)
    if not box or region == "auto":
        lons = [c[0] for _, c in coords] or [0]; lats = [c[1] for _, c in coords] or [50]
        pad = 4; box = (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)
    # expand box to include all markers
    if coords:
        lons = [c[0] for _, c in coords]; lats = [c[1] for _, c in coords]
        box = (min(box[0], min(lons) - 3), min(box[1], min(lats) - 3), max(box[2], max(lons) + 3), max(box[3], max(lats) + 3))
    im, d = base(th, n, tot)
    fx0, fy0, fx1, fy1 = MARGIN, 150, W - MARGIN, H - 90
    fw, fh = fx1 - fx0, fy1 - fy0
    # optional coastline geojson
    gj = th.root / "assets" / "maps" / "world.geojson"
    if gj.exists():
        import json
        try:
            data = json.loads(gj.read_text())
            for feat in data.get("features", []):
                geom = feat.get("geometry", {}); polys = geom.get("coordinates", [])
                if geom.get("type") == "Polygon": polys = [polys]
                for poly in polys:
                    for ring in poly:
                        pts = []
                        for lon, lat in ring:
                            px, py = _project(lon, max(min(lat, 84), -84), box); pts.append((fx0 + px * fw, fy0 + py * fh))
                        if len(pts) > 2: d.polygon(pts, fill=(24, 28, 36), outline=(60, 66, 78))
        except Exception: pass
    else:
        for gx in range(int(box[0]) // 5 * 5, int(box[2]) + 5, 5):
            px, _ = _project(gx, box[1], box); d.line([(fx0 + px * fw, fy0), (fx0 + px * fw, fy1)], fill=(24, 27, 34), width=1)
        for gy in range(int(box[1]) // 5 * 5, int(box[3]) + 5, 5):
            if gy <= -85 or gy >= 85: continue
            _, py = _project(box[0], gy, box); d.line([(fx0, fy0 + py * fh), (fx1, fy0 + py * fh)], fill=(24, 27, 34), width=1)
    d.rectangle([fx0, fy0, fx1, fy1], outline=th.rail, width=2)
    frames = [(im.copy(), min(1.0, dur * 0.1))]; used = frames[0][1]
    step = (dur * 0.7) / max(len(coords), 1); prev = im; fl = th.font("body", 30); label_boxes = []
    for name, (lon, lat) in coords:
        px, py = _project(lon, lat, box); x, y = fx0 + px * fw, fy0 + py * fh
        cur = prev.copy(); dd = ImageDraw.Draw(cur)
        dd.ellipse([x - 16, y - 16, x + 16, y + 16], outline=th.accent, width=2)
        dd.ellipse([x - 7, y - 7, x + 7, y + 7], fill=th.accent)
        tw = dd.textlength(name, font=fl)
        cands = [(x + 24, y - 20), (x - 24 - tw, y - 20), (x - tw / 2, y + 22), (x - tw / 2, y - 58)]
        placed = None
        for tx, ty in cands:
            box_ = (tx, ty, tx + tw, ty + 36)
            if box_[0] < fx0 or box_[2] > fx1: continue
            if all(box_[2] < b[0] or box_[0] > b[2] or box_[3] < b[1] or box_[1] > b[3] for b in label_boxes):
                placed = box_; break
        if placed is None: placed = (cands[0][0], cands[0][1], cands[0][0] + tw, cands[0][1] + 36)
        label_boxes.append(placed)
        dd.text((placed[0], placed[1]), name, font=fl, fill=th.fg)
        fr = fade_frames(prev, cur, 0.3); frames += fr; used += 0.3
        if step - 0.3 > 0: frames.append((cur, step - 0.3)); used += step - 0.3
        prev = cur
    if dur - used > 0: frames.append((prev, dur - used))
    return frames


def sc_sources(th, sc: Scene, dur, n, tot, script: Script | None = None):
    im, d = base(th, n, tot)
    d.text((MARGIN, 150), sc.attrs.get("title", "Sources"), font=th.font("head", 64), fill=th.fg)
    d.text((MARGIN, 250), "Full list with links in the description.", font=th.font("body", 34), fill=th.muted)
    srcs = (script.sources if script else [])[:14]
    fb = th.font("body", 26); y = 330
    for s in srcs:
        s2 = s.split(" — ")[0].split(" - http")[0]
        s2 = s2 if len(s2) < 120 else s2[:118] + "…"
        d.text((MARGIN, y), "· " + s2, font=fb, fill=th.fg); y += 44
        if y > H - 100: break
    im0, _ = base(th, n, tot)
    return fade_frames(im0, im, 0.6) + [(im, max(0.1, dur - 0.6))]


def sc_outro(th, sc: Scene, dur, n, tot):
    im, d = base(th)
    t = th.brand
    f = th.font("head", 96); d.text(((W - d.textlength(t, font=f)) / 2, 380), t, font=f, fill=th.fg)
    d.line([(W / 2 - 90, 520), (W / 2 + 90, 520)], fill=th.accent, width=4)
    sub = sc.attrs.get("title", "") if sc.attrs.get("title", "") != th.brand else ""
    s2 = sc.attrs.get("next", "New episode every Tuesday and Friday.")
    fs = th.font("body", 36); d.text(((W - d.textlength(s2, font=fs)) / 2, 560), s2, font=fs, fill=th.muted)
    im0, _ = base(th)
    return fade_frames(im0, im, 0.8) + [(im, max(0.1, dur - 0.8))]


RENDERERS = {"title": sc_title, "text": sc_text, "quote": sc_quote, "chart": sc_chart, "timeline": sc_timeline,
             "map": sc_map, "sources": sc_sources, "outro": sc_outro}


def render_scene(th, sc: Scene, dur, n, tot, script=None):
    fn = RENDERERS.get(sc.type, sc_text)
    if sc.type == "sources": return fn(th, sc, dur, n, tot, script)
    return fn(th, sc, dur, n, tot)


def build_video(script: Script, th: Theme, workdir: Path, out_mp4: Path, audio_wav: Path, cfg: dict):
    """script.scenes must have .duration set. Renders keyframes, writes concat list, runs ffmpeg."""
    frames_dir = workdir / "frames"; frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.png"): old.unlink()
    lst = []; idx = 0; tot = len(script.scenes); t = 0.0
    gap = 0.35  # short fade to bg between scenes
    prev_last = None
    for sc in script.scenes:
        sc.start = t
        frames = render_scene(th, sc, sc.duration - gap, sc.n, tot, script)
        if prev_last is not None:
            for im, d in fade_frames(prev_last, frames[0][0], gap):
                p = frames_dir / f"f{idx:05d}.png"; im.save(p, compress_level=1); lst.append((p, d)); idx += 1
        else:
            t += 0  # first scene: no lead-in
            im0, _ = base(th); p = frames_dir / f"f{idx:05d}.png"; im0.save(p); lst.append((p, gap)); idx += 1
        for im, d in frames:
            p = frames_dir / f"f{idx:05d}.png"; im.save(p, compress_level=1); lst.append((p, d)); idx += 1
        prev_last = frames[-1][0]
        t += sc.duration
    total = sum(d for _, d in lst)
    concat = workdir / "concat.txt"
    with open(concat, "w") as f:
        for p, d in lst:
            f.write(f"file '{p.as_posix()}'\nduration {max(d, 1/FPS):.4f}\n")
        f.write(f"file '{lst[-1][0].as_posix()}'\n")
    # progress bar + chapter labels via ffmpeg filters
    vf = [f"scale={W}:{H}", "format=yuv420p",
          f"drawbox=x=0:y=ih-6:w='iw*t/{total:.3f}':h=6:color=0x{'%02x%02x%02x' % th.accent}@0.9:t=fill"]
    chap_font = th.fontfiles.get("bold", th.fontfiles["body"])
    if script.chapters:
        # chapter i spans from scene start to next chapter start
        starts = []
        for scn, title in script.chapters:
            s = next((x.start for x in script.scenes if x.n == scn), None)
            if s is not None: starts.append((s, title))
        starts.sort()
        for i, (s, title) in enumerate(starts):
            e = starts[i + 1][0] if i + 1 < len(starts) else total
            if i == 0 and s < 1: continue  # don't label the cold open
            tt = title.replace("'", "’").replace(":", "\\:").replace(",", "\\,")
            vf.append(f"drawtext=fontfile='{chap_font}':text='{tt}':fontsize=24:fontcolor=0x{'%02x%02x%02x' % th.muted}"
                      f":x={MARGIN}:y=h-48:enable='between(t,{s:.2f},{e:.2f})'")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats", "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(audio_wav),
           "-vf", ",".join(vf), "-r", str(FPS), "-c:v", "libx264", "-preset", cfg.get("preset", "medium"), "-crf", "18",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_mp4)]
    subprocess.run(cmd, check=True)
    return total
