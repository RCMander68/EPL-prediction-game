# ⚽ Matchday — Premier League Predictor

A single-page football prediction game for a friends-and-family league.
Sibling to the Hit Paydirt NFL app; same architecture, football-specific parts.

## How it works (one paragraph)
One self-contained `index.html` on free GitHub Pages, backed by Firebase
(identity + saved picks only), fed by a Python script that GitHub Actions runs
on a schedule to pull EPL data from API-Football and commit it as JSON. Players
read the JSON; nobody calls the API directly. Everything scores off the feed's
**team id**, never the club name.

## Layout
- `index.html` — the entire app
- `data/season.json` — season config
- `data/2026/week-NN.json` — per-gameweek fixtures + scores (id-keyed)
- `data/divisions.json` — every division's clubs with their API-Football ids
- `data/standings.json` — live tables (powers provisional scoring)
- `data/HOW-TO-EDIT.md` — hand-entry guide for when the feed breaks
- `scripts/fetch_results.py` — the fetcher (validate hard, id-based)
- `scripts/validate_data.py` — guards every data change in CI
- `.github/workflows/` — scheduled fetch + validate-on-change
- `firestore.rules` — ALL games' rules (deploy whole file via Firebase console)
- `LOCKED-BUILD-SPEC.md` — every design decision, the source of truth

## Setup
1. Get a free API-Football key at api-football.com.
2. In the GitHub repo: Settings → Secrets → Actions → add `API_FOOTBALL_KEY`.
3. Run the fetcher once to populate real ids + times:
   `API_FOOTBALL_KEY=xxxx python scripts/fetch_results.py --map-only`
   then `python scripts/fetch_results.py`.
4. Enable GitHub Pages (Settings → Pages → deploy from branch, root).
5. Publish `firestore.rules` in the Firebase console (paste the WHOLE file —
   it contains the World Cup, NFL and EPL blocks; never paste just one).

## The rules
- 3 points exact score, 1 correct result, 0 wrong.
- Champion pick 5 points; each correct promotion/relegation club 3 (any order).
- Each match locks at its own kickoff.
- From 10 games to go, season picks score provisionally ("if the season ended
  today") in a separate projected column.

## When the feed breaks
The app keeps running on the last good data and GitHub emails you. Hand-enter
the week or table following `data/HOW-TO-EDIT.md`. Expect this ~once a season.
