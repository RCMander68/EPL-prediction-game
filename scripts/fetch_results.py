#!/usr/bin/env python3
"""
fetch_results.py — Matchday EPL predictor data fetcher.

Pulls fixtures + standings for the English pyramid from API-Football and
writes them into data/ as JSON. Everything is keyed by the feed's STABLE
numeric team id, never by club name — this is what makes scoring immune to
spelling/abbreviation drift ("Wolves" vs "Wolverhampton Wanderers").

Design principles (from the Hit Paydirt hand-off):
  * Validate HARD. A response that fails a sanity check is REFUSED, not saved.
    The league keeps running on the last good data. A bad fetch does nothing.
  * Fail LOUD. On any refusal we exit non-zero so GitHub Actions emails you.
  * Never trust names. Match on team id.

Auth: reads the key from the API_FOOTBALL_KEY environment variable.
      (In GitHub Actions this comes from a repository secret — never commit it.)

Usage:
    API_FOOTBALL_KEY=xxxx python scripts/fetch_results.py            # normal run
    API_FOOTBALL_KEY=xxxx python scripts/fetch_results.py --map-only # rebuild divisions.json id map
    API_FOOTBALL_KEY=xxxx python scripts/fetch_results.py --season 2026
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

API_BASE = "https://v3.football.api-sports.io"
DATA = Path(__file__).resolve().parent.parent / "data"

# The divisions we care about, top of the pyramid down to the National League.
# league_id is resolved automatically from the /leagues endpoint on first run
# (we do NOT hardcode ids from memory — only the Premier League's is well-known
# as 39, used as a sanity anchor). Keys are our internal slugs.
DIVISIONS = [
    {"slug": "premier_league", "name": "Premier League", "country": "England", "anchor_id": 39},
    {"slug": "championship",   "name": "Championship",    "country": "England", "anchor_id": None},
    {"slug": "league_one",     "name": "League One",      "country": "England", "anchor_id": None},
    {"slug": "league_two",     "name": "League Two",      "country": "England", "anchor_id": None},
    {"slug": "national_league", "name": "National League", "country": "England", "anchor_id": None},
]

# ---------------------------------------------------------------------------
# Low-level API helper
# ---------------------------------------------------------------------------
def _key():
    k = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not k:
        die("API_FOOTBALL_KEY is not set. Get a free key at api-football.com and "
            "export it (or set it as a GitHub Actions secret).")
    return k

def api_get(endpoint, params):
    """GET one endpoint. Respects the 10-req/min free limit with a small sleep."""
    # urlencode escapes spaces and other special characters (e.g. "Premier League"
    # -> "Premier%20League"). Building the query by hand would put raw spaces in
    # the URL, which is illegal and raises InvalidURL.
    qs = urlencode(params)
    url = f"{API_BASE}/{endpoint}?{qs}"
    req = Request(url, headers={"x-apisports-key": _key()})
    try:
        with urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        die(f"HTTP {e.code} calling {endpoint} ({qs}). Feed may be down or rate-limited.")
    except URLError as e:
        die(f"Network error calling {endpoint}: {e.reason}")
    # API-Football returns errors in-band as a dict/list under "errors".
    errs = payload.get("errors")
    if errs:
        die(f"API returned errors for {endpoint} ({qs}): {errs}")
    time.sleep(6.5)  # stay comfortably under 10 requests/minute
    return payload

def die(msg):
    """Fail loud: print to stderr and exit non-zero so CI emails the alarm."""
    print(f"FETCH REFUSED: {msg}", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# League id resolution (name -> id, verified against country)
# ---------------------------------------------------------------------------
def resolve_league_ids(season):
    """Look up each division's league id from the /leagues endpoint."""
    resolved = {}
    for d in DIVISIONS:
        # API-Football forbids using `search` and `country` together in one
        # /leagues call, so we search by name only and filter by country below.
        payload = api_get("leagues", {"search": d["name"]})
        matches = [x for x in payload.get("response", [])
                   if x["league"]["name"].lower() == d["name"].lower()
                   and x["country"]["name"].lower() == d["country"].lower()]
        if not matches:
            die(f"Could not resolve league id for {d['name']} ({d['country']}).")
        lid = matches[0]["league"]["id"]
        # Sanity anchor: the Premier League MUST be id 39. If not, the feed
        # changed something fundamental — refuse rather than guess.
        if d["anchor_id"] and lid != d["anchor_id"]:
            die(f"{d['name']} resolved to id {lid}, expected {d['anchor_id']}. Refusing.")
        # Verify this league/season actually covers standings before we rely on it.
        seasons = matches[0].get("seasons", [])
        cov = next((s for s in seasons if s.get("year") == season), None)
        if cov and not cov.get("coverage", {}).get("standings", False):
            print(f"  ! {d['name']} {season} has no standings coverage — "
                  f"promotion/relegation for this tier will need hand-entry.", file=sys.stderr)
        resolved[d["slug"]] = lid
        print(f"  {d['name']:16} -> league id {lid}")
    return resolved

# ---------------------------------------------------------------------------
# Teams (build the name <-> id map)
# ---------------------------------------------------------------------------
def fetch_teams(league_id, season):
    payload = api_get("teams", {"league": league_id, "season": season})
    teams = []
    for row in payload.get("response", []):
        t = row["team"]
        teams.append({"id": t["id"], "name": t["name"]})
    return teams

def build_divisions_map(season):
    """Write data/divisions.json: every division's clubs WITH their team ids."""
    print(f"Resolving league ids for season {season}...")
    ids = resolve_league_ids(season)
    out = {"season": season, "divisions": {}}
    for d in DIVISIONS:
        lid = ids[d["slug"]]
        teams = fetch_teams(lid, season)
        # Championship-and-above should be 24 (or 20 for the PL); warn if not,
        # but don't die — early pre-season the feed can be incomplete.
        expected = 20 if d["slug"] == "premier_league" else 24
        if teams and len(teams) != expected:
            print(f"  ! {d['name']}: got {len(teams)} teams (expected {expected}).",
                  file=sys.stderr)
        out["divisions"][d["slug"]] = {
            "name": d["name"], "league_id": lid,
            "teams": sorted(teams, key=lambda x: x["name"]),
        }
        print(f"  {d['name']:16} -> {len(teams)} teams")
    _write(DATA / "divisions.json", out)
    print("Wrote data/divisions.json")

# ---------------------------------------------------------------------------
# Fixtures  (one file per gameweek: data/2026/week-NN.json)
# ---------------------------------------------------------------------------
def fetch_fixtures(league_id, season):
    payload = api_get("fixtures", {"league": league_id, "season": season})
    return payload.get("response", [])

def write_weeks(season):
    """Fetch PL fixtures and split them into per-gameweek files, keyed by team id."""
    ids = resolve_league_ids(season)
    pl = ids["premier_league"]
    fixtures = fetch_fixtures(pl, season)
    if not fixtures:
        die("Premier League fixtures came back empty. Refusing to overwrite.")

    weeks = {}
    for fx in fixtures:
        rnd = fx["league"]["round"]                       # e.g. "Regular Season - 5"
        try:
            gw = int(rnd.rsplit("-", 1)[1].strip())
        except (IndexError, ValueError):
            continue                                       # skip non-league rounds
        home, away = fx["teams"]["home"], fx["teams"]["away"]
        goals = fx["goals"]
        status = fx["fixture"]["status"]["short"]          # NS, FT, etc.
        weeks.setdefault(gw, []).append({
            "fixtureId": fx["fixture"]["id"],
            "kickoffUtc": fx["fixture"]["date"],           # ISO 8601 w/ offset
            "status": status,
            "home": {"id": home["id"], "name": home["name"]},
            "away": {"id": away["id"], "name": away["name"]},
            # scores are null until played; validator guards these
            "score": {"h": goals["home"], "a": goals["away"]},
        })

    validate_weeks(weeks)
    for gw, matches in sorted(weeks.items()):
        matches.sort(key=lambda m: m["kickoffUtc"])
        _write(DATA / "2026" / f"week-{gw:02d}.json",
               {"season": season, "gameweek": gw, "fixtures": matches})
    print(f"Wrote {len(weeks)} gameweek files to data/2026/")

# ---------------------------------------------------------------------------
# Standings (data/standings.json — powers provisional scoring + settlement)
# ---------------------------------------------------------------------------
def fetch_standings(league_id, season):
    payload = api_get("standings", {"league": league_id, "season": season})
    resp = payload.get("response", [])
    if not resp:
        return []
    table = resp[0]["league"]["standings"][0]
    return [{"rank": r["rank"], "id": r["team"]["id"], "name": r["team"]["name"],
             "played": r["all"]["played"], "points": r["points"]} for r in table]

def write_standings(season):
    ids = resolve_league_ids(season)
    out = {"season": season, "divisions": {}}
    for d in DIVISIONS:
        table = fetch_standings(ids[d["slug"]], season)
        out["divisions"][d["slug"]] = {"name": d["name"], "table": table}
        print(f"  {d['name']:16} -> {len(table)} rows")
    _write(DATA / "standings.json", out)
    print("Wrote data/standings.json")

# ---------------------------------------------------------------------------
# Hard validation
# ---------------------------------------------------------------------------
def validate_weeks(weeks):
    if not weeks:
        die("No gameweeks parsed from fixtures. Refusing.")
    for gw, matches in weeks.items():
        for m in matches:
            for side in ("home", "away"):
                if not isinstance(m[side]["id"], int):
                    die(f"GW{gw}: {side} team id is not an int ({m[side]}).")
            sc = m["score"]
            for k in ("h", "a"):
                v = sc[k]
                if v is not None and (not isinstance(v, int) or v < 0 or v > 30):
                    die(f"GW{gw}: implausible score {sc} for fixture {m['fixtureId']}.")
            if m["home"]["id"] == m["away"]["id"]:
                die(f"GW{gw}: a team is playing itself ({m['home']}).")

# ---------------------------------------------------------------------------
def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026, help="4-digit season key (2026 = 2026/27)")
    ap.add_argument("--map-only", action="store_true", help="only rebuild divisions.json id map")
    args = ap.parse_args()

    if args.map_only:
        build_divisions_map(args.season)
        return
    # Normal scheduled run: refresh fixtures, standings; (re)build the map if missing.
    if not (DATA / "divisions.json").exists():
        build_divisions_map(args.season)
    write_weeks(args.season)
    write_standings(args.season)
    print("Fetch complete.")

if __name__ == "__main__":
    main()
