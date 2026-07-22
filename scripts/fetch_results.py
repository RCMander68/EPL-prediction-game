#!/usr/bin/env python3
"""
fetch_results.py — Matchday EPL fetcher (football-data.org edition).

Pulls Premier League + Championship fixtures, results and standings from
football-data.org (free tier) and writes them into data/ as JSON.

WHY football-data.org: its free tier is designed around CURRENT-season
coverage for 12 competitions incl. the Premier League (code "PL") and the
Championship (code "ELC"). That is the opposite of API-Football's free tier,
which locks the current season behind a paid plan.

FAIL-SAFE BY DESIGN. The app does NOT depend on this script. If the feed is
unavailable, rate-limited, or (worst case) the current season isn't on the
free tier, this script exits WITHOUT overwriting good data. The app keeps
running on whatever is already committed, and the scorer can enter results by
hand / paste them in-app. The feed is an ACCELERATOR, never a dependency.

Lower divisions (League One, League Two, National League) are NOT fetched here
-- they're entered in-app by pasting a final league table (scorer tool). This
feed only does the two divisions the free tier covers.

Auth: reads the token from the FOOTBALL_DATA_TOKEN environment variable
      (a GitHub Actions secret; never commit it).

Usage:
    FOOTBALL_DATA_TOKEN=xxxx python scripts/fetch_results.py
    FOOTBALL_DATA_TOKEN=xxxx python scripts/fetch_results.py --season 2026
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API_BASE = "https://api.football-data.org/v4"
DATA = Path(__file__).resolve().parent.parent / "data"

# football-data.org competition codes (free tier)
COMPETITIONS = {
    "premier_league": "PL",    # Premier League
    "championship":   "ELC",   # EFL Championship
}

def die(msg, soft=False):
    """Fail loud. soft=True means 'nothing was written, app unaffected'."""
    prefix = "FETCH SKIPPED (app unaffected)" if soft else "FETCH REFUSED"
    print(f"{prefix}: {msg}", file=sys.stderr)
    sys.exit(1)

def token():
    t = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
    if not t:
        die("FOOTBALL_DATA_TOKEN is not set. Get a free token at football-data.org "
            "and set it as a GitHub Actions secret.")
    return t

def api_get(path, params=None):
    url = f"{API_BASE}/{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"X-Auth-Token": token()})
    try:
        with urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 403:
            die(f"HTTP 403 for {path} -- the free tier may not cover this season/resource. "
                f"The app keeps running on existing data; enter results in-app instead.", soft=True)
        if e.code == 429:
            die(f"HTTP 429 rate-limited on {path}. Nothing written; will retry next run.", soft=True)
        die(f"HTTP {e.code} for {path}.", soft=True)
    except URLError as e:
        die(f"Network error for {path}: {e.reason}. Nothing written.", soft=True)
    time.sleep(6.5)  # free tier: 10 requests/minute
    return payload

def fetch_standings(code, season):
    payload = api_get(f"competitions/{code}/standings", {"season": season})
    tables = payload.get("standings", [])
    total = next((t for t in tables if t.get("type") == "TOTAL"), None)
    if not total:
        return []
    out = []
    for r in total.get("table", []):
        team = r.get("team", {})
        out.append({
            "rank": r.get("position"),
            "id": team.get("id"),
            "name": team.get("name"),
            "played": r.get("playedGames"),
            "points": r.get("points"),
        })
    return out

def write_standings(season):
    out = {"season": season, "source": "football-data.org", "divisions": {}}
    for slug, code in COMPETITIONS.items():
        table = fetch_standings(code, season)
        out["divisions"][slug] = {"name": slug, "table": table}
        print(f"  {slug:16} -> {len(table)} rows")
    if all(len(d["table"]) == 0 for d in out["divisions"].values()):
        die("All standings came back empty. Refusing to overwrite good data.", soft=True)
    _write(DATA / "standings.json", out)
    print("Wrote data/standings.json")

def fetch_matches(code, season):
    payload = api_get(f"competitions/{code}/matches", {"season": season})
    return payload.get("matches", [])

def write_weeks(season):
    matches = fetch_matches(COMPETITIONS["premier_league"], season)
    if not matches:
        die("Premier League matches came back empty. Refusing to overwrite.", soft=True)
    weeks = {}
    for m in matches:
        gw = m.get("matchday")
        if not gw:
            continue
        home, away = m.get("homeTeam", {}), m.get("awayTeam", {})
        score = m.get("score", {}).get("fullTime", {})
        weeks.setdefault(gw, []).append({
            "fixtureId": m.get("id"),
            "kickoffUtc": m.get("utcDate"),
            "status": m.get("status"),
            "home": {"id": home.get("id"), "name": home.get("name")},
            "away": {"id": away.get("id"), "name": away.get("name")},
            "score": {"h": score.get("home"), "a": score.get("away")},
        })
    validate_weeks(weeks)
    for gw, fixtures in sorted(weeks.items()):
        fixtures.sort(key=lambda f: f["kickoffUtc"] or "")
        _write(DATA / "2026" / f"week-{gw:02d}.json",
               {"season": season, "gameweek": gw, "fixtures": fixtures})
    print(f"Wrote {len(weeks)} gameweek files to data/2026/")

def validate_weeks(weeks):
    if not weeks:
        die("No gameweeks parsed from fixtures. Refusing.", soft=True)
    for gw, fixtures in weeks.items():
        for m in fixtures:
            sc = m["score"]
            played = sc["h"] is not None or sc["a"] is not None
            for side in ("home", "away"):
                tid = m[side]["id"]
                if played and not isinstance(tid, int):
                    die(f"GW{gw}: team id missing on a played match -- refusing.", soft=True)
            for k in ("h", "a"):
                v = sc[k]
                if v is not None and (not isinstance(v, int) or v < 0 or v > 30):
                    die(f"GW{gw}: implausible score {sc}.", soft=True)
            if m["home"]["id"] and m["home"]["id"] == m["away"]["id"]:
                die(f"GW{gw}: a team is playing itself.", soft=True)

def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026, help="season start year (2026 = 2026/27)")
    args = ap.parse_args()
    print(f"Fetching PL + Championship for season {args.season} from football-data.org...")
    write_weeks(args.season)
    write_standings(args.season)
    print("Fetch complete.")

if __name__ == "__main__":
    main()

