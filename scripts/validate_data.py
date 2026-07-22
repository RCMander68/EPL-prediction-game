#!/usr/bin/env python3
"""
validate_data.py — the guard rail for the committed JSON.

Runs in CI (via .github/workflows/validate.yml) on ANY change under data/,
whether from the scheduled fetcher or a human hand-edit during a feed break.
If anything looks wrong it exits non-zero and GitHub emails you — the same
alarm the fetcher uses. This is what lets you safely hand-enter scores when
the feed breaks without fear of silently corrupting the league.

Checks:
  * every week file parses, has a gameweek + a list of fixtures
  * every fixture references integer team ids (scoring is id-based)
  * scores are either null or a plausible integer 0..30
  * no team plays itself; kickoff timestamps parse
  * divisions.json maps every club to an integer id (no name-only entries)
"""

import json
import sys
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
errors = []

def err(msg):
    errors.append(msg)

def check_week_file(p):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return err(f"{p.name}: not valid JSON ({e})")
    if not isinstance(d.get("gameweek"), int):
        err(f"{p.name}: missing/invalid 'gameweek'")
    fixtures = d.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        return err(f"{p.name}: 'fixtures' must be a non-empty list")
    for i, m in enumerate(fixtures):
        loc = f"{p.name}[{i}]"
        sc = m.get("score", {})
        played = sc.get("h") is not None or sc.get("a") is not None
        for side in ("home", "away"):
            t = m.get(side, {})
            tid = t.get("id")
            # Pre-fetch scaffold fixtures may have null ids (not yet resolved).
            # But once a score exists, ids MUST be integers — scoring is id-based.
            if played and not isinstance(tid, int):
                err(f"{loc}: {side}.id must be an integer once a score exists")
            elif tid is not None and not isinstance(tid, int):
                err(f"{loc}: {side}.id must be an integer or null, got {tid!r}")
        hid, aid = m.get("home", {}).get("id"), m.get("away", {}).get("id")
        if hid is not None and hid == aid:
            err(f"{loc}: a team is playing itself")
        for k in ("h", "a"):
            v = sc.get(k)
            if v is not None and (not isinstance(v, int) or v < 0 or v > 30):
                err(f"{loc}: implausible score {sc}")
        ko = m.get("kickoffUtc", "")
        try:
            datetime.fromisoformat(ko.replace("Z", "+00:00"))
        except Exception:
            err(f"{loc}: kickoffUtc does not parse ({ko!r})")

def check_divisions():
    p = DATA / "divisions.json"
    if not p.exists():
        return  # optional until first fetch
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return err(f"divisions.json: not valid JSON ({e})")
    for slug, div in d.get("divisions", {}).items():
        for t in div.get("teams", []):
            tid = t.get("id")
            # null allowed in the pre-fetch scaffold; once set it must be an int.
            if tid is not None and not isinstance(tid, int):
                err(f"divisions.json[{slug}]: '{t.get('name')}' id must be int or null")

def check_lower_csv():
    p = DATA / "divisions_lower.csv"
    if not p.exists():
        return  # optional
    valid_divs = {"League One", "League Two"}
    lines = p.read_text(encoding="utf-8").splitlines()
    if not lines:
        return err("divisions_lower.csv: empty")
    header = [c.strip().lower() for c in lines[0].split(",")]
    if header[:2] != ["division", "club"]:
        err("divisions_lower.csv: header must be 'division,club'")
    seen = set()
    for i, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = [c.strip() for c in line.split(",")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            err(f"divisions_lower.csv line {i}: needs division,club")
            continue
        div, club = parts[0], parts[1]
        if div not in valid_divs:
            err(f"divisions_lower.csv line {i}: unknown division '{div}'")
        key = (div, club.lower())
        if key in seen:
            err(f"divisions_lower.csv line {i}: duplicate '{club}' in {div}")
        seen.add(key)

def main():
    week_files = sorted((DATA / "2026").glob("week-*.json"))
    if not week_files:
        print("No week files yet — nothing to validate.")
    for p in week_files:
        check_week_file(p)
    check_divisions()
    check_lower_csv()

    if errors:
        print("DATA VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        sys.exit(1)
    print(f"Validation passed ({len(week_files)} week files).")

if __name__ == "__main__":
    main()

