#!/usr/bin/env python3
"""Cron entry point: produce + schedule the next unpublished script for the next free publish slot.
Run every few hours:   0 */6 * * *  cd /path/nordic-ledger && python3 pipeline/schedule.py >> logs/schedule.log 2>&1
Guarantees: never more than cfg.compliance.max_uploads_per_week; only scripts that pass compliance_check.
"""
from __future__ import annotations
import json, subprocess, sys, datetime as dt
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent; ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from parse import parse_script
from run import compliance_check

DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def slots(cfg, start: dt.datetime, n=20):
    days = [DAYS[d] for d in cfg["channel"]["publish_days"]]
    hh, mm = map(int, cfg["channel"]["publish_time_utc"].split(":"))
    d = start.date(); out = []
    while len(out) < n:
        if d.weekday() in days:
            t = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=dt.timezone.utc)
            if t > start + dt.timedelta(hours=6): out.append(t)
        d += dt.timedelta(days=1)
    return out


def main():
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    now = dt.datetime.now(dt.timezone.utc)
    taken = set(); recent = 0
    for up in (ROOT / "out").glob("*/upload.json"):
        j = json.loads(up.read_text())
        if j.get("publish_at"): taken.add(j["publish_at"])
        if now.timestamp() - j.get("uploaded", 0) < 7 * 86400: recent += 1
    if recent >= int(cfg["compliance"].get("max_uploads_per_week", 3)):
        print(now.isoformat(), "weekly cap reached; nothing to do"); return
    free = [s for s in slots(cfg, now) if s.isoformat().replace("+00:00", "Z") not in taken]
    for sp in sorted((ROOT / "scripts").glob("*.md")):
        s = parse_script(sp)
        outdir = ROOT / "out" / f"{s.id}-{s.slug}"
        if (outdir / "upload.json").exists(): continue
        probs = compliance_check(s)
        if probs:
            print(now.isoformat(), f"skip {sp.name}: {probs}"); continue
        publish_at = free[0].isoformat().replace("+00:00", "Z")
        print(now.isoformat(), f"producing {sp.name} → publish {publish_at}")
        r = subprocess.run([sys.executable, str(HERE / "run.py"), str(sp), "--upload", "--publish-at", publish_at])
        if r.returncode != 0:
            print(now.isoformat(), f"FAILED {sp.name} rc={r.returncode}")
        return
    print(now.isoformat(), "no unpublished scripts – write more")


if __name__ == "__main__":
    main()
