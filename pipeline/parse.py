"""Parse a Nordic Ledger script (.md) into structured scenes.

Format:
---
<yaml front matter>
---
## SCENE n | type=<type> | key="value" | key2=value2
```csv            (optional, for chart/timeline)
...
```
Narration paragraph(s)

## CHAPTERS
1: Title
5: Title

## SOURCES
1. ... — https://...
"""
from __future__ import annotations
import re, csv, io, yaml
from dataclasses import dataclass, field
from pathlib import Path

SCENE_RE = re.compile(r"^## SCENE\s+(\d+)\s*\|\s*(.*)$")
ATTR_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^|]+))')


@dataclass
class Scene:
    n: int
    type: str
    attrs: dict
    narration: str
    data: list[dict] = field(default_factory=list)
    # filled later
    audio: str | None = None
    duration: float = 0.0
    start: float = 0.0


@dataclass
class Script:
    meta: dict
    scenes: list[Scene]
    chapters: list[tuple[int, str]]
    sources: list[str]
    path: Path

    @property
    def id(self): return str(self.meta.get("id", "000")).zfill(3)
    @property
    def slug(self): return self.meta.get("slug", "video")
    @property
    def title(self):
        t = self.meta.get("title_options") or [self.meta.get("title", "Untitled")]
        return t[0]


def _parse_attrs(s: str) -> dict:
    out = {}
    for m in ATTR_RE.finditer(s):
        k = m.group(1)
        v = next(g for g in m.groups()[1:] if g is not None)
        out[k] = v.strip()
    return out


def parse_script(path: str | Path) -> Script:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    meta = {}
    if text.startswith("---"):
        _, fm, text = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}

    lines = text.splitlines()
    scenes: list[Scene] = []
    chapters: list[tuple[int, str]] = []
    sources: list[str] = []
    mode = None  # 'scene' | 'chapters' | 'sources'
    cur: Scene | None = None
    buf: list[str] = []
    in_csv = False
    csv_buf: list[str] = []

    def flush():
        nonlocal cur, buf, csv_buf
        if cur is not None:
            cur.narration = "\n".join(l for l in buf).strip()
            cur.narration = re.sub(r"\n{2,}", "\n\n", cur.narration)
            if csv_buf:
                rdr = csv.DictReader(io.StringIO("\n".join(csv_buf)))
                cur.data = [dict(r) for r in rdr]
            scenes.append(cur)
        cur, buf, csv_buf = None, [], []

    for line in lines:
        m = SCENE_RE.match(line)
        if m:
            flush(); mode = "scene"
            attrs = _parse_attrs(m.group(2))
            cur = Scene(n=int(m.group(1)), type=attrs.pop("type", "text"), attrs=attrs, narration="")
            continue
        if line.strip() == "## CHAPTERS":
            flush(); mode = "chapters"; continue
        if line.strip() == "## SOURCES":
            flush(); mode = "sources"; continue
        if mode == "scene":
            if line.strip().startswith("```"):
                in_csv = not in_csv
                continue
            if in_csv:
                if line.strip(): csv_buf.append(line.strip())
            else:
                buf.append(line)
        elif mode == "chapters":
            mm = re.match(r"^\s*(?:-\s*)?(?:Scenes?\s*)?(\d+)(?:\s*[-–]\s*\d+)?\s*[:|]\s*(.+)$", line, re.I)
            if mm: chapters.append((int(mm.group(1)), mm.group(2).strip().strip('"')))
        elif mode == "sources":
            mm = re.match(r"^\s*\d+[.)]\s*(.+)$", line)
            if mm: sources.append(mm.group(1).strip())
    flush()
    return Script(meta=meta, scenes=scenes, chapters=chapters, sources=sources, path=path)


def narration_words(s: Script) -> int:
    return sum(len(sc.narration.split()) for sc in s.scenes)


if __name__ == "__main__":
    import sys
    s = parse_script(sys.argv[1])
    print(s.id, s.slug, s.title)
    print(len(s.scenes), "scenes;", narration_words(s), "words;", len(s.chapters), "chapters;", len(s.sources), "sources")
    for sc in s.scenes:
        print(f"  {sc.n:>2} {sc.type:<9} {len(sc.narration.split()):>4}w  data={len(sc.data)} {list(sc.attrs)[:3]}")
